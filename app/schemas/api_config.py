from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=4000)
    source_url: str = Field(default="", max_length=1000)
    document_text: str = Field(default="", max_length=2_000_000)
    document_name: str = Field(default="", max_length=240)
    source_type: str = Field(default="openapi", max_length=40)

    @field_validator("name", "base_url", "description", "source_url", "document_text", "document_name", "source_type")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()


class ApiServerUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name", "base_url", "description")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ApiServerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    base_url: str
    created_at: datetime
    updated_at: datetime
    source_count: int = 0
    endpoint_count: int = 0


class ApiDocumentationImportRequest(BaseModel):
    source_url: str = Field(default="", max_length=1000)
    source_type: str = Field(default="openapi", max_length=40)
    base_url: str = Field(default="", max_length=1000)
    document_text: str = Field(default="", max_length=2_000_000)
    document_name: str = Field(default="", max_length=240)

    @field_validator("source_url", "source_type", "base_url", "document_text", "document_name")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()


class ApiDocumentationSourcePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID | None
    source_type: str
    source_url: str
    title: str
    version: str
    base_url: str
    status: str
    raw_document: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ApiEndpointCreateRequest(BaseModel):
    method: str = Field(min_length=3, max_length=12)
    path: str = Field(min_length=1, max_length=1000)
    summary: str = Field(default="", max_length=240)
    description: str = Field(default="", max_length=4000)
    operation_id: str = Field(default="", max_length=240)
    auth_required: bool = False
    auth_type: str = Field(default="", max_length=120)
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    request_body: dict[str, Any] = Field(default_factory=dict)
    responses: dict[str, Any] = Field(default_factory=dict)
    is_accessible_to_ai: bool = False

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        method = value.upper().strip()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
            raise ValueError("Unsupported HTTP method")
        return method

    @field_validator("path", "summary", "description", "operation_id", "auth_type")
    @classmethod
    def strip_strings(cls, value: str) -> str:
        return value.strip()


class ApiEndpointUpdateRequest(BaseModel):
    method: str | None = Field(default=None, min_length=3, max_length=12)
    path: str | None = Field(default=None, min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    operation_id: str | None = Field(default=None, max_length=240)
    auth_required: bool | None = None
    auth_type: str | None = Field(default=None, max_length=120)
    parameters: list[dict[str, Any]] | None = None
    request_body: dict[str, Any] | None = None
    responses: dict[str, Any] | None = None
    is_accessible_to_ai: bool | None = None

    @field_validator("method")
    @classmethod
    def normalize_optional_method(cls, value: str | None) -> str | None:
        if value is None:
            return None
        method = value.upper().strip()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
            raise ValueError("Unsupported HTTP method")
        return method

    @field_validator("path", "summary", "description", "operation_id", "auth_type")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ApiEndpointPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    server_id: UUID | None
    source_id: UUID | None
    method: str
    path: str
    summary: str
    description: str
    operation_id: str
    auth_required: bool
    auth_type: str
    parameters: list[dict[str, Any]]
    request_body: dict[str, Any]
    responses: dict[str, Any]
    is_accessible_to_ai: bool
    created_at: datetime
    updated_at: datetime


class ApiConfiguratorPublic(BaseModel):
    servers: list[ApiServerPublic]


class ApiServerDetailPublic(BaseModel):
    server: ApiServerPublic
    sources: list[ApiDocumentationSourcePublic]
    endpoints: list[ApiEndpointPublic]
