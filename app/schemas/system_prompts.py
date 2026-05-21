"""Pydantic schemas for per-tenant system prompt management (US-14 T2)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SystemPromptRollbackRequest(BaseModel):
    """Body for POST /api/v1/system-prompt/rollback."""

    revision_id: UUID


class SystemPromptUpsertRequest(BaseModel):
    """Body for PUT /api/v1/system-prompt.

    Content is the only field — there's one prompt per company so no name,
    no preset id needed in v1. Capped at 8000 chars to keep token budgets
    sane; LightRAG's user_prompt has to leave room for retrieved context.
    """

    content: str = Field(min_length=1, max_length=8000)


class SystemPromptRevisionPublic(BaseModel):
    """One entry in the version history list."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    content: str
    updated_by_user_id: UUID | None
    created_at: datetime


class SystemPromptPublic(BaseModel):
    """Response for GET / PUT.

    `is_default` is True when the tenant hasn't set a custom prompt and is
    being served the built-in fallback. In that case `id`, `updated_at`,
    and `updated_by_user_id` are None — there's no DB row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID | None
    company_id: UUID
    content: str
    is_default: bool
    updated_by_user_id: UUID | None
    created_at: datetime | None
    updated_at: datetime | None
