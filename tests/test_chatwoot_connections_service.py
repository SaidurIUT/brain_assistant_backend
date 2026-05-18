"""
Tests for the chatwoot_connections service layer (US-03 backend).

Focused on the pure / mockable parts: token masking, duplicate detection,
and the public-dict shape. Endpoint-level integration (auth + DB) is left
to manual curl/Postman testing since the test suite has no test-DB fixture.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.chatwoot_connections import (
    _mask_token,
    connection_public_dict,
    create_connection,
    update_connection,
)


# ─── _mask_token ─────────────────────────────────────────


def test_mask_token_shows_last_four() -> None:
    assert _mask_token("sk-1234567890aFIx") == "****aFIx"


def test_mask_token_handles_short_tokens() -> None:
    assert _mask_token("abc") == "***"


def test_mask_token_handles_none_and_empty() -> None:
    assert _mask_token(None) == ""
    assert _mask_token("") == ""


# ─── connection_public_dict ──────────────────────────────


def test_public_dict_masks_token_and_reports_secret_presence() -> None:
    record = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        chatwoot_base_url="http://chatwoot.local:3000",
        chatwoot_account_id=1,
        chatwoot_inbox_id=2,
        chatwoot_agent_bot_id=3,
        chatwoot_agent_bot_token="sk-secret-value-aFIx",
        webhook_secret="whsec-12345",
        status="active",
        last_health_check_at=None,
        created_at=None,
        updated_at=None,
    )
    public = connection_public_dict(record)
    assert public["chatwoot_agent_bot_token_masked"] == "****aFIx"
    assert public["webhook_secret_set"] is True
    # The full raw token must never appear anywhere in the public dict
    for value in public.values():
        assert "sk-secret-value-aFIx" not in str(value)


def test_public_dict_handles_missing_webhook_secret() -> None:
    record = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        chatwoot_base_url="http://x",
        chatwoot_account_id=1,
        chatwoot_inbox_id=1,
        chatwoot_agent_bot_id=1,
        chatwoot_agent_bot_token="tok",
        webhook_secret=None,
        status="active",
        last_health_check_at=None,
        created_at=None,
        updated_at=None,
    )
    assert connection_public_dict(record)["webhook_secret_set"] is False


# ─── duplicate detection on create ───────────────────────


def test_create_raises_409_when_account_inbox_pair_already_exists() -> None:
    company = SimpleNamespace(id=uuid4())
    db = MagicMock()
    # _find_duplicate returns an existing row
    db.scalar.return_value = SimpleNamespace(id=uuid4())

    with pytest.raises(HTTPException) as excinfo:
        create_connection(
            db,
            company=company,
            chatwoot_base_url="http://chatwoot.local",
            chatwoot_account_id=1,
            chatwoot_inbox_id=1,
            chatwoot_agent_bot_id=1,
            chatwoot_agent_bot_token="tok",
            webhook_secret=None,
        )

    assert excinfo.value.status_code == 409
    assert "already exists" in excinfo.value.detail.lower()


def test_create_strips_trailing_slash_from_base_url() -> None:
    company = SimpleNamespace(id=uuid4())
    db = MagicMock()
    db.scalar.return_value = None  # no duplicate

    create_connection(
        db,
        company=company,
        chatwoot_base_url="http://chatwoot.local:3000/",
        chatwoot_account_id=1,
        chatwoot_inbox_id=1,
        chatwoot_agent_bot_id=1,
        chatwoot_agent_bot_token="tok",
        webhook_secret=None,
    )

    added_record = db.add.call_args.args[0]
    assert added_record.chatwoot_base_url == "http://chatwoot.local:3000"


# ─── update: 409 on (account, inbox) collision with sibling row ──────


def test_update_raises_409_if_new_pair_collides_with_sibling() -> None:
    company = SimpleNamespace(id=uuid4())
    db = MagicMock()
    record = SimpleNamespace(
        id=uuid4(),
        chatwoot_account_id=1,
        chatwoot_inbox_id=10,
        chatwoot_base_url="http://x",
        chatwoot_agent_bot_id=1,
        chatwoot_agent_bot_token="tok",
        webhook_secret=None,
        status="active",
    )
    db.scalar.return_value = SimpleNamespace(id=uuid4())

    with pytest.raises(HTTPException) as excinfo:
        update_connection(
            db,
            record=record,
            company=company,
            chatwoot_base_url=None,
            chatwoot_account_id=1,
            chatwoot_inbox_id=20,
            chatwoot_agent_bot_id=None,
            chatwoot_agent_bot_token=None,
            webhook_secret=None,
            status_value=None,
        )

    assert excinfo.value.status_code == 409


def test_update_skips_duplicate_check_when_pair_unchanged() -> None:
    company = SimpleNamespace(id=uuid4())
    db = MagicMock()
    record = SimpleNamespace(
        id=uuid4(),
        chatwoot_account_id=1,
        chatwoot_inbox_id=10,
        chatwoot_base_url="http://x",
        chatwoot_agent_bot_id=1,
        chatwoot_agent_bot_token="tok",
        webhook_secret=None,
        status="active",
    )

    update_connection(
        db,
        record=record,
        company=company,
        chatwoot_base_url=None,
        chatwoot_account_id=None,
        chatwoot_inbox_id=None,
        chatwoot_agent_bot_id=None,
        chatwoot_agent_bot_token="new-token-aFIx",
        webhook_secret=None,
        status_value=None,
    )

    db.scalar.assert_not_called()
    assert record.chatwoot_agent_bot_token == "new-token-aFIx"
