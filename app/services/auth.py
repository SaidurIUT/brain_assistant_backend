from dataclasses import dataclass
from datetime import timedelta
from secrets import token_urlsafe
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.datetime import utc_now
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.models import AuthAuditEvent, AuthEmailToken, AuthSession, CompanyMember, User
from app.schemas.auth import AcceptInvitationRequest, ResetPasswordRequest, RegisterRequest
from app.services.email import frontend_url, send_email
from app.services.settings import create_default_workspace


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


def request_user_agent(request: Request) -> str | None:
    user_agent = request.headers.get("user-agent")
    return user_agent[:512] if user_agent else None


def audit_event(
    db: Session,
    *,
    event_type: str,
    request: Request,
    user_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuthAuditEvent(
            user_id=user_id,
            event_type=event_type,
            ip_address=request_ip(request),
            user_agent=request_user_agent(request),
            event_metadata=metadata or {},
        )
    )


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=refresh_token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=f"{settings.api_v1_prefix}/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path=f"{settings.api_v1_prefix}/auth",
    )


def create_user(db: Session, payload: RegisterRequest, request: Request) -> User:
    now = utc_now()
    user = User(
        email=str(payload.email),
        email_normalized=normalize_email(str(payload.email)),
        first_name=payload.first_name,
        last_name=payload.last_name,
        password_hash=hash_password(payload.password),
        password_changed_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    audit_event(db, event_type="user_registered", request=request, user_id=user.id)
    return user


def create_email_token(
    db: Session,
    *,
    email: str,
    purpose: str,
    user_id: UUID | None = None,
    company_member_id: UUID | None = None,
) -> str:
    token = token_urlsafe(48)
    expiry = (
        utc_now() + timedelta(days=settings.invitation_expire_days)
        if purpose == "invitation"
        else utc_now() + timedelta(hours=settings.email_verification_expire_hours)
    )
    db.add(
        AuthEmailToken(
            user_id=user_id,
            company_member_id=company_member_id,
            email=email,
            email_normalized=normalize_email(email),
            token_hash=hash_refresh_token(token),
            purpose=purpose,
            expires_at=expiry,
        )
    )
    return token


def send_verification_email(user: User, token: str) -> None:
    link = frontend_url("/verify-email", token=token)
    send_email(
        to_email=user.email,
        subject="Verify your Brain Assistant email",
        text_body=(
            f"Hi {user.first_name},\n\n"
            "Verify your Brain Assistant account by opening this link:\n"
            f"{link}\n\n"
            f"This link expires in {settings.email_verification_expire_hours} hours."
        ),
    )


def send_invitation_email(member: CompanyMember, token: str) -> None:
    link = frontend_url("/invite/accept", token=token)
    inviter = "An administrator"
    company_name = member.company.name
    send_email(
        to_email=member.email,
        subject=f"You were invited to {company_name} on Brain Assistant",
        text_body=(
            f"Hi {member.first_name or member.email},\n\n"
            f"{inviter} invited you to {company_name} on Brain Assistant.\n"
            "Set your password and accept the invite here:\n"
            f"{link}\n\n"
            f"This invitation expires in {settings.invitation_expire_days} days."
        ),
    )


def send_password_reset_email(user: User, token: str) -> None:
    link = frontend_url("/reset-password", token=token)
    send_email(
        to_email=user.email,
        subject="Reset your Brain Assistant password",
        text_body=(
            f"Hi {user.first_name},\n\n"
            "Reset your Brain Assistant password by opening this link:\n"
            f"{link}\n\n"
            f"This link expires in {settings.email_verification_expire_hours} hours."
        ),
    )


def register_user(db: Session, payload: RegisterRequest, request: Request) -> AuthResult:
    email_normalized = normalize_email(str(payload.email))
    user = db.scalar(select(User).where(User.email_normalized == email_normalized))

    if user is None:
        user = create_user(db, payload, request)
        create_default_workspace(db, user)
    elif not verify_password(payload.password, user.password_hash):
        audit_event(db, event_type="login_failed", request=request, user_id=user.id, metadata={"reason": "registration_existing_email"})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Use the password for this account to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.email_verified_at is None:
        token = create_email_token(db, email=user.email, purpose="verification", user_id=user.id)
        send_verification_email(user, token)
        audit_event(db, event_type="verification_email_sent", request=request, user_id=user.id)

    result = create_auth_result(db, user, request)
    audit_event(db, event_type="login_success", request=request, user_id=user.id, metadata={"reason": "registration"})
    db.commit()
    db.refresh(user)
    return result


def create_auth_result(db: Session, user: User, request: Request) -> AuthResult:
    refresh_token = token_urlsafe(64)
    refresh_family = uuid4()
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        refresh_token_family=refresh_family,
        ip_address=request_ip(request),
        user_agent=request_user_agent(request),
        expires_at=utc_now() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    access_token, _ = create_access_token(
        subject=user.id,
        email=user.email,
        is_superuser=user.is_superuser,
    )
    return AuthResult(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


def login_user(db: Session, *, email: str, password: str, request: Request) -> AuthResult:
    user = db.scalar(select(User).where(User.email_normalized == normalize_email(email)))
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if user is None:
        audit_event(db, event_type="login_failed", request=request, metadata={"reason": "unknown_email"})
        db.commit()
        raise invalid_credentials

    now = utc_now()
    if user.locked_until and user.locked_until > now:
        audit_event(db, event_type="login_blocked", request=request, user_id=user.id)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked. Please try again later.",
        )

    if not user.is_active or not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_lockout_after_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
        audit_event(db, event_type="login_failed", request=request, user_id=user.id)
        db.commit()
        raise invalid_credentials

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    result = create_auth_result(db, user, request)
    audit_event(db, event_type="login_success", request=request, user_id=user.id)
    db.commit()
    db.refresh(user)
    return result


def token_record(db: Session, *, raw_token: str, purpose: str) -> AuthEmailToken:
    record = db.scalar(
        select(AuthEmailToken).where(
            AuthEmailToken.token_hash == hash_refresh_token(raw_token),
            AuthEmailToken.purpose == purpose,
        )
    )
    if record is None or record.consumed_at is not None or record.expires_at <= utc_now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    return record


def verify_email_token(db: Session, *, raw_token: str, request: Request) -> AuthResult:
    record = token_record(db, raw_token=raw_token, purpose="verification")
    user = db.get(User, record.user_id) if record.user_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token")

    user.email_verified_at = user.email_verified_at or utc_now()
    record.consumed_at = utc_now()
    audit_event(db, event_type="email_verified", request=request, user_id=user.id)
    result = create_auth_result(db, user, request)
    audit_event(db, event_type="login_success", request=request, user_id=user.id, metadata={"reason": "email_verified"})
    db.commit()
    db.refresh(user)
    return result


def accept_invitation(db: Session, *, payload: AcceptInvitationRequest, request: Request) -> AuthResult:
    record = token_record(db, raw_token=payload.token, purpose="invitation")
    member = db.get(CompanyMember, record.company_member_id) if record.company_member_id else None
    if member is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invitation token")

    user = member.user or db.scalar(select(User).where(User.email_normalized == member.email_normalized))
    if user is None:
        now = utc_now()
        user = User(
            email=member.email,
            email_normalized=member.email_normalized,
            first_name=payload.first_name or member.first_name or "New",
            last_name=payload.last_name or member.last_name or "Member",
            password_hash=hash_password(payload.password),
            email_verified_at=now,
            password_changed_at=now,
        )
        db.add(user)
        db.flush()
        audit_event(db, event_type="user_created_from_invitation", request=request, user_id=user.id)
    else:
        user.email_verified_at = user.email_verified_at or utc_now()

    member.user_id = user.id
    member.first_name = member.first_name or user.first_name
    member.last_name = member.last_name or user.last_name
    member.status = "active"
    record.consumed_at = utc_now()
    audit_event(
        db,
        event_type="invitation_accepted",
        request=request,
        user_id=user.id,
        metadata={"company_id": str(member.company_id), "member_id": str(member.id)},
    )
    result = create_auth_result(db, user, request)
    audit_event(db, event_type="login_success", request=request, user_id=user.id, metadata={"reason": "invitation"})
    db.commit()
    db.refresh(user)
    return result


def create_invitation_for_member(db: Session, member: CompanyMember) -> None:
    token = create_email_token(
        db,
        email=member.email,
        purpose="invitation",
        user_id=member.user_id,
        company_member_id=member.id,
    )
    send_invitation_email(member, token)


def request_password_reset(db: Session, *, email: str, request: Request) -> None:
    user = db.scalar(select(User).where(User.email_normalized == normalize_email(email)))
    if user is None or not user.is_active:
        audit_event(db, event_type="password_reset_requested", request=request, metadata={"email": normalize_email(email)})
        db.commit()
        return

    token = create_email_token(db, email=user.email, purpose="password_reset", user_id=user.id)
    send_password_reset_email(user, token)
    audit_event(db, event_type="password_reset_requested", request=request, user_id=user.id)
    db.commit()


def reset_password(db: Session, *, payload: ResetPasswordRequest, request: Request) -> None:
    record = token_record(db, raw_token=payload.token, purpose="password_reset")
    user = db.get(User, record.user_id) if record.user_id else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password reset token")

    now = utc_now()
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = now
    user.failed_login_count = 0
    user.locked_until = None
    record.consumed_at = now
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    audit_event(db, event_type="password_reset_completed", request=request, user_id=user.id)
    db.commit()


def refresh_auth_session(db: Session, *, refresh_token: str, request: Request) -> AuthResult:
    token_hash = hash_refresh_token(refresh_token)
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash))
    invalid_token = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if session is None:
        audit_event(db, event_type="refresh_failed", request=request, metadata={"reason": "unknown_token"})
        db.commit()
        raise invalid_token

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        revoke_session_family(db, session.refresh_token_family)
        audit_event(db, event_type="refresh_failed", request=request, user_id=session.user_id, metadata={"reason": "inactive_user"})
        db.commit()
        raise invalid_token

    now = utc_now()
    if session.revoked_at is not None:
        revoke_session_family(db, session.refresh_token_family)
        audit_event(db, event_type="refresh_reuse_detected", request=request, user_id=user.id)
        db.commit()
        raise invalid_token

    if session.expires_at <= now:
        session.revoked_at = now
        audit_event(db, event_type="refresh_failed", request=request, user_id=user.id, metadata={"reason": "expired"})
        db.commit()
        raise invalid_token

    new_refresh_token = token_urlsafe(64)
    session.revoked_at = now
    session.last_used_at = now
    new_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(new_refresh_token),
        refresh_token_family=session.refresh_token_family,
        rotated_from_session_id=session.id,
        ip_address=request_ip(request),
        user_agent=request_user_agent(request),
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(new_session)
    access_token, _ = create_access_token(
        subject=user.id,
        email=user.email,
        is_superuser=user.is_superuser,
    )
    audit_event(db, event_type="refresh_success", request=request, user_id=user.id)
    db.commit()
    db.refresh(user)
    return AuthResult(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


def revoke_session_family(db: Session, refresh_token_family: UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.refresh_token_family == refresh_token_family, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )


def logout_session(db: Session, *, refresh_token: str, request: Request) -> None:
    session = db.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(refresh_token))
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = utc_now()
        audit_event(db, event_type="logout", request=request, user_id=session.user_id)
    db.commit()


def logout_all_sessions(db: Session, *, user: User, request: Request) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    audit_event(db, event_type="logout_all", request=request, user_id=user.id)
    db.commit()


def change_password(db: Session, *, user: User, current_password: str, new_password: str, request: Request) -> None:
    if not verify_password(current_password, user.password_hash):
        audit_event(db, event_type="password_change_failed", request=request, user_id=user.id)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    user.password_hash = hash_password(new_password)
    user.password_changed_at = utc_now()
    logout_all_sessions(db, user=user, request=request)
    audit_event(db, event_type="password_changed", request=request, user_id=user.id)
    db.commit()
