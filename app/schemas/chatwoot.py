"""Pydantic schemas for the Chatwoot connection management API (US-03 backend)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_serializer


class ChatwootConnectionCreate(BaseModel):
    """Body for POST /api/v1/chatwoot/connections.

    All fields the admin copies out of their Chatwoot setup. The
    chatwoot_agent_bot_token and webhook_secret are secrets — they're
    accepted here but never echoed back in full.
    """

    chatwoot_base_url: HttpUrl
    chatwoot_account_id: int = Field(ge=1)
    chatwoot_inbox_id: int = Field(ge=1)
    chatwoot_agent_bot_id: int = Field(ge=1)
    chatwoot_agent_bot_token: str = Field(min_length=1, max_length=500)
    webhook_secret: str | None = Field(default=None, max_length=500)

    @field_serializer("chatwoot_base_url")
    def _serialize_url(self, v: HttpUrl) -> str:
        return str(v)


class ChatwootConnectionUpdate(BaseModel):
    """Body for PATCH /api/v1/chatwoot/connections/{id}.

    All fields optional — admin can rotate just the token, or change just
    the inbox id without re-supplying the URL.
    """

    chatwoot_base_url: HttpUrl | None = None
    chatwoot_account_id: int | None = Field(default=None, ge=1)
    chatwoot_inbox_id: int | None = Field(default=None, ge=1)
    chatwoot_agent_bot_id: int | None = Field(default=None, ge=1)
    chatwoot_agent_bot_token: str | None = Field(default=None, min_length=1, max_length=500)
    webhook_secret: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=50)


class ChatwootConnectionPublic(BaseModel):
    """Response shape for GET / POST / PATCH.

    Tokens are masked (last 4 chars only) so a leaked log line or PR
    screenshot doesn't expose them. The full value lives in postgres for
    the worker to read.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    chatwoot_base_url: str
    chatwoot_account_id: int
    chatwoot_inbox_id: int
    chatwoot_agent_bot_id: int
    chatwoot_agent_bot_token_masked: str
    webhook_secret_set: bool
    status: str
    last_health_check_at: datetime | None
    created_at: datetime
    updated_at: datetime
