from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Brain Assistant Auth API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

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

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        if self.environment.lower() in {"production", "prod"}:
            weak_markers = {"change-me", "replace-this", "dev-only"}
            if any(marker in self.secret_key.lower() for marker in weak_markers):
                raise ValueError("SECRET_KEY must be a strong random value in production")
            if not self.auth_cookie_secure:
                raise ValueError("AUTH_COOKIE_SECURE must be true in production")
        return self

    @property
    def cors_origin_strings(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
