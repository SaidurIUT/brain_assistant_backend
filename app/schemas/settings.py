from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.auth import UserPublic

Role = Literal["administrator", "manager", "agent", "viewer"]


class CompanyPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    industry: str
    team_size: str
    description: str
    primary_language: str


class CompanyUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    industry: str = Field(default="Other", max_length=120)
    team_size: str = Field(default="1-5 agents", max_length=80)
    description: str = Field(default="", max_length=4000)
    primary_language: str = Field(default="English", max_length=80)

    @field_validator("name", "industry", "team_size", "description", "primary_language")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()


class BrandPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workspace_name: str
    assistant_name: str
    widget_greeting: str
    primary_color: str
    accent_color: str
    widget_background: str
    logo_url: str


class BrandUpdateRequest(BaseModel):
    workspace_name: str = Field(min_length=1, max_length=160)
    assistant_name: str = Field(min_length=1, max_length=160)
    widget_greeting: str = Field(min_length=1, max_length=260)
    primary_color: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_color: str = Field(default="#06b6d4", pattern=r"^#[0-9a-fA-F]{6}$")
    widget_background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: str = Field(default="", max_length=500)

    @field_validator("workspace_name", "assistant_name", "widget_greeting", "logo_url")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()


class MemberPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    role: Role
    status: str
    created_at: datetime


class WorkspaceSummaryPublic(BaseModel):
    id: UUID
    name: str
    role: Role
    status: str


class MemberCreateRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    role: Role = "agent"

    @field_validator("first_name", "last_name")
    @classmethod
    def strip_names(cls, value: str) -> str:
        return value.strip()


class MemberRoleUpdateRequest(BaseModel):
    role: Role


class SettingsPublic(BaseModel):
    user: UserPublic
    company: CompanyPublic
    brand: BrandPublic
    members: list[MemberPublic]
    workspaces: list[WorkspaceSummaryPublic]
    current_role: Role
