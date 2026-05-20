from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    AcceptInvitationRequest,
    AuthContextPublic,
    AuthWorkspacePublic,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    KeycloakExchangeRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserPublic,
    VerifyEmailRequest,
)
from app.services.auth import (
    accept_invitation,
    audit_event,
    change_password,
    clear_refresh_cookie,
    create_auth_result,
    login_user,
    logout_all_sessions,
    logout_session,
    refresh_auth_session,
    register_user,
    request_password_reset,
    reset_password,
    set_refresh_cookie,
    verify_email_token,
)
from app.api.deps import get_current_user
from app.services.keycloak import (
    KeycloakTokenExchangeError,
    decode_keycloak_id_token,
    exchange_authorization_code,
    provision_user_from_keycloak_payload,
)
from app.services.settings import active_workspace_memberships

router = APIRouter(prefix="/auth", tags=["auth"])


def require_local_auth() -> None:
    if settings.auth_provider == "keycloak":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password authentication is managed by Keycloak for this deployment.",
        )


@router.get("/provider")
def auth_provider() -> dict[str, str]:
    return {
        "provider": settings.auth_provider,
        "keycloak_issuer": settings.keycloak_issuer if settings.auth_provider == "keycloak" else "",
        "keycloak_client_id": settings.keycloak_client_id if settings.auth_provider == "keycloak" else "",
    }


def auth_context_public(db: Session, user: User) -> AuthContextPublic:
    memberships = active_workspace_memberships(db, user)
    return AuthContextPublic(
        user=UserPublic.model_validate(user),
        workspaces=[
            AuthWorkspacePublic(
                id=member.company.id,
                name=member.company.name,
                role=member.role,
                status=member.status,
            )
            for member in memberships
        ],
    )


def require_keycloak_auth() -> None:
    if settings.auth_provider != "keycloak":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Keycloak auth is not enabled for this deployment.",
        )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    require_local_auth()
    result = register_user(db, payload, request)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/keycloak/exchange", response_model=TokenResponse)
async def exchange_keycloak_code(
    payload: KeycloakExchangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    require_keycloak_auth()
    try:
        keycloak_token = await exchange_authorization_code(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
            code_verifier=payload.code_verifier,
        )
        id_token = keycloak_token.get("id_token")
        if not id_token:
            raise KeycloakTokenExchangeError("Keycloak did not return an identity token")
        keycloak_payload = decode_keycloak_id_token(str(id_token))
    except KeycloakTokenExchangeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = provision_user_from_keycloak_payload(
        db,
        keycloak_payload,
        request=request,
        create_workspace=False,
    )
    result = create_auth_result(db, user, request)
    audit_event(
        db,
        event_type="login_success",
        request=request,
        user_id=user.id,
        metadata={"reason": "keycloak_exchange"},
    )
    db.commit()
    db.refresh(user)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(user),
    )


@router.post("/verify-email", response_model=TokenResponse)
def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    require_local_auth()
    result = verify_email_token(db, raw_token=payload.token, request=request)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/accept-invitation", response_model=TokenResponse)
def accept_workspace_invitation(
    payload: AcceptInvitationRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    require_local_auth()
    result = accept_invitation(db, payload=payload, request=request)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    require_local_auth()
    result = login_user(db, email=str(payload.email), password=payload.password, request=request)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    require_local_auth()
    request_password_reset(db, email=str(payload.email), request=request)
    return MessageResponse(message="If that email exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
def reset_account_password(
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MessageResponse:
    require_local_auth()
    reset_password(db, payload=payload, request=request)
    clear_refresh_cookie(response)
    return MessageResponse(message="Password reset. Please log in.")


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = Body(default=None),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    db: Session = Depends(get_db),
) -> TokenResponse:
    refresh_token = payload.refresh_token if payload else None
    refresh_token = refresh_token or refresh_cookie
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = refresh_auth_session(db, refresh_token=refresh_token, request=request)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    payload: LogoutRequest | None = Body(default=None),
    refresh_cookie: str | None = Cookie(default=None, alias=settings.auth_cookie_name),
    db: Session = Depends(get_db),
) -> MessageResponse:
    refresh_token = payload.refresh_token if payload else None
    refresh_token = refresh_token or refresh_cookie
    if refresh_token:
        logout_session(db, refresh_token=refresh_token, request=request)
    clear_refresh_cookie(response)
    return MessageResponse(message="Logged out")


@router.post("/logout-all", response_model=MessageResponse)
def logout_all(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    logout_all_sessions(db, user=current_user, request=request)
    clear_refresh_cookie(response)
    return MessageResponse(message="All sessions logged out")


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@router.get("/context", response_model=AuthContextPublic)
def auth_context(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AuthContextPublic:
    return auth_context_public(db, current_user)


@router.post("/change-password", response_model=MessageResponse)
def update_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    require_local_auth()
    change_password(
        db,
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        request=request,
    )
    clear_refresh_cookie(response)
    return MessageResponse(message="Password changed. Please log in again.")
