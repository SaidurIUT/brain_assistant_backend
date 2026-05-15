from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.datetime import utc_now
from app.models import CompanyMember, User
from app.services.auth import audit_event, normalize_email
from app.services.settings import create_default_workspace


@lru_cache(maxsize=1)
def jwks_client() -> PyJWKClient:
    return PyJWKClient(settings.keycloak_effective_jwks_url)


def decode_keycloak_token(token: str) -> dict[str, Any]:
    if settings.auth_provider != "keycloak":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Keycloak auth is not enabled")

    try:
        signing_key = jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iat", "sub"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Keycloak access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token_client = payload.get("azp") or payload.get("client_id")
    audiences = payload.get("aud", [])
    if isinstance(audiences, str):
        audiences = [audiences]
    if settings.keycloak_client_id not in {*audiences, token_client}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Keycloak token was not issued for this application",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def user_from_keycloak_token(db: Session, token: str, request: Request | None = None) -> User:
    payload = decode_keycloak_token(token)
    subject = str(payload["sub"])
    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Keycloak token is missing email")

    normalized = normalize_email(str(email))
    user = db.scalar(select(User).where(User.keycloak_subject == subject))
    if user is None:
        user = db.scalar(select(User).where(User.email_normalized == normalized))

    now = utc_now()
    if user is None:
        user = User(
            email=str(email),
            email_normalized=normalized,
            keycloak_subject=subject,
            first_name=_claim_name(payload, "given_name", "New"),
            last_name=_claim_name(payload, "family_name", "Member"),
            password_hash="keycloak-managed",
            email_verified_at=now if payload.get("email_verified") else None,
            password_changed_at=now,
            last_login_at=now,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Could not provision Keycloak user") from exc
        _activate_invited_memberships(db, user)
        db.flush()
        if not _has_membership(db, user):
            create_default_workspace(db, user)
        if request is not None:
            audit_event(db, event_type="keycloak_user_provisioned", request=request, user_id=user.id)
    else:
        user.keycloak_subject = user.keycloak_subject or subject
        user.email = str(email)
        user.email_normalized = normalized
        user.first_name = _claim_name(payload, "given_name", user.first_name)
        user.last_name = _claim_name(payload, "family_name", user.last_name)
        user.email_verified_at = user.email_verified_at or (now if payload.get("email_verified") else None)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        _activate_invited_memberships(db, user)
        db.flush()
        if not _has_membership(db, user):
            create_default_workspace(db, user)
        if request is not None:
            audit_event(db, event_type="keycloak_login_success", request=request, user_id=user.id)

    db.commit()
    db.refresh(user)
    return user


def _claim_name(payload: dict[str, Any], key: str, fallback: str) -> str:
    value = str(payload.get(key) or "").strip()
    if value:
        return value[:100]
    name = str(payload.get("name") or "").strip()
    if not name:
        return fallback
    parts = name.split(maxsplit=1)
    if key == "given_name":
        return parts[0][:100]
    if len(parts) > 1:
        return parts[1][:100]
    return fallback


def _activate_invited_memberships(db: Session, user: User) -> None:
    members = db.scalars(
        select(CompanyMember).where(
            CompanyMember.email_normalized == user.email_normalized,
            CompanyMember.status == "invited",
            or_(CompanyMember.user_id.is_(None), CompanyMember.user_id == user.id),
        )
    ).all()
    for member in members:
        member.user_id = user.id
        member.first_name = member.first_name or user.first_name
        member.last_name = member.last_name or user.last_name
        member.status = "active"


def _has_membership(db: Session, user: User) -> bool:
    return bool(db.scalar(select(func.count()).select_from(CompanyMember).where(CompanyMember.user_id == user.id)))
