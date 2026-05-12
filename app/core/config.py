from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Brain Assistant Auth API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    docs_url: str = "/docs"
    redoc_url: str = "/redoc"
    openapi_url: str = "/openapi.json"
    frontend_base_url: str = Field(default="http://localhost:3010", alias="FRONTEND_BASE_URL")

    database_url: str = Field(alias="DATABASE_URL")
    secret_key: str = Field(alias="SECRET_KEY", min_length=32)
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=30, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    backend_cors_origins: str = Field(default="", alias="BACKEND_CORS_ORIGINS")
    auth_cookie_name: str = "brain_assistant_refresh_token"
    auth_cookie_secure: bool = Field(default=True, alias="AUTH_COOKIE_SECURE")
    auth_cookie_samesite: str = "lax"

    login_lockout_after_failures: int = 8
    login_lockout_minutes: int = 15

    mail_mode: str = Field(default="dev", alias="MAIL_MODE")
    mail_from: str = Field(default="Brain Assistant <no-reply@brainassistant.local>", alias="MAIL_FROM")
    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1125, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=False, alias="SMTP_USE_TLS")
    smtp_starttls: bool = Field(default=False, alias="SMTP_STARTTLS")
    email_verification_expire_hours: int = Field(default=24, alias="EMAIL_VERIFICATION_EXPIRE_HOURS")
    invitation_expire_days: int = Field(default=7, alias="INVITATION_EXPIRE_DAYS")
    upload_storage_path: str = Field(default="storage/uploads", alias="UPLOAD_STORAGE_PATH")
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, alias="UPLOAD_MAX_BYTES")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    celery_task_eager_propagates: bool = Field(default=False, alias="CELERY_TASK_EAGER_PROPAGATES")

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.environment.lower() in {"production", "prod"}:
            weak_markers = {"change-me", "replace-this", "dev-only"}
            if any(marker in self.secret_key.lower() for marker in weak_markers):
                raise ValueError("SECRET_KEY must be a strong random value in production")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        if self.mail_mode.lower() in {"production", "prod"}:
            if not self.smtp_host:
                raise ValueError("SMTP_HOST is required in production mail mode")
            if not self.smtp_username or not self.smtp_password:
                raise ValueError("SMTP_USERNAME and SMTP_PASSWORD are required in production mail mode")
            if "brainassistant.local" in self.mail_from:
                raise ValueError("MAIL_FROM must be a real sender address in production mail mode")
        return self

    @property
    def cors_origin_strings(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
