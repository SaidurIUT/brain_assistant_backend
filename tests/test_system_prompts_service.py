"""
Tests for the per-tenant system prompt service (US-14).

Covers the pure / mockable parts: fallback to default, prompt_public_dict
shape (is_default flag), resolve_prompt_content's never-raise guarantee.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.system_prompts import (
    DEFAULT_SYSTEM_PROMPT,
    prompt_public_dict,
    resolve_prompt_content,
    resolve_prompt_content_by_company_id,
)


def _make_company():
    return SimpleNamespace(id=uuid4())


# ─── prompt_public_dict ─────────────────────────────────


def test_public_dict_returns_default_when_no_record() -> None:
    company = _make_company()
    result = prompt_public_dict(None, company)
    assert result["is_default"] is True
    assert result["content"] == DEFAULT_SYSTEM_PROMPT
    assert result["id"] is None
    assert result["updated_at"] is None
    assert result["company_id"] == company.id


def test_public_dict_returns_custom_when_record_exists() -> None:
    company = _make_company()
    record = SimpleNamespace(
        id=uuid4(),
        company_id=company.id,
        content="You are NFS Bot. Be formal.",
        updated_by_user_id=uuid4(),
        created_at=None,
        updated_at=None,
    )
    result = prompt_public_dict(record, company)
    assert result["is_default"] is False
    assert result["content"] == "You are NFS Bot. Be formal."
    assert result["id"] == record.id


# ─── resolve_prompt_content ─────────────────────────────


def test_resolve_returns_default_when_no_custom_prompt() -> None:
    db = MagicMock()
    db.scalar.return_value = None  # no row for this company
    company = _make_company()
    assert resolve_prompt_content(db, company) == DEFAULT_SYSTEM_PROMPT


def test_resolve_returns_custom_content_when_set() -> None:
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(content="custom voice")
    company = _make_company()
    assert resolve_prompt_content(db, company) == "custom voice"


def test_resolve_falls_back_to_default_on_db_exception() -> None:
    """Worker must never crash on a prompt fetch — falls back to default."""
    db = MagicMock()
    db.scalar.side_effect = RuntimeError("db unavailable")
    company = _make_company()
    assert resolve_prompt_content(db, company) == DEFAULT_SYSTEM_PROMPT


def test_resolve_ignores_blank_content() -> None:
    """Empty/whitespace custom content treated as 'no prompt set'."""
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(content="   ")
    company = _make_company()
    assert resolve_prompt_content(db, company) == DEFAULT_SYSTEM_PROMPT


# ─── resolve_prompt_content_by_company_id (worker path) ──────


def test_resolve_by_company_id_returns_custom() -> None:
    db = MagicMock()
    db.scalar.return_value = SimpleNamespace(content="Acme tone")
    assert resolve_prompt_content_by_company_id(db, uuid4()) == "Acme tone"


def test_resolve_by_company_id_falls_back_on_exception() -> None:
    db = MagicMock()
    db.scalar.side_effect = Exception("conn dropped")
    assert (
        resolve_prompt_content_by_company_id(db, uuid4()) == DEFAULT_SYSTEM_PROMPT
    )
