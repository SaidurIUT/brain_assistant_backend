from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import User
from app.schemas.auth import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    ForgotPasswordRequest,
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
    change_password,
    clear_refresh_cookie,
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

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    result = register_user(db, payload, request)
    set_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=result.expires_in,
        user=UserPublic.model_validate(result.user),
    )


@router.post("/verify-email", response_model=TokenResponse)
def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
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
    request_password_reset(db, email=str(payload.email), request=request)
    return MessageResponse(message="If that email exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
def reset_account_password(
    payload: ResetPasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MessageResponse:
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


@router.post("/change-password", response_model=MessageResponse)
def update_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    change_password(
        db,
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        request=request,
    )
    clear_refresh_cookie(response)
    return MessageResponse(message="Password changed. Please log in again.")
