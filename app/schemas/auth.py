from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    is_active: bool
    created_at: datetime


class UserUpdateRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_update_names(cls, value: str) -> str:
        return value.strip()


class RegisterRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_names(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_passwords(self) -> "RegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        validate_password_strength(self.password)
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=32, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)
    confirm_password: str = Field(min_length=12, max_length=256)

    @model_validator(mode="after")
    def validate_passwords(self) -> "ChangePasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        if self.current_password == self.new_password:
            raise ValueError("New password must be different from the current password")
        validate_password_strength(self.new_password)
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class MessageResponse(BaseModel):
    message: str


def validate_password_strength(password: str) -> None:
    checks = [
        any(char.islower() for char in password),
        any(char.isupper() for char in password),
        any(char.isdigit() for char in password),
        any(not char.isalnum() for char in password),
    ]
    if sum(checks) < 3:
        raise ValueError(
            "Password must include at least three of: lowercase, uppercase, number, symbol"
        )
