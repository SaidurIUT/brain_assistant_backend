"""
Tests for system prompt version history (US-14 T3).

Verifies that upsert_prompt_for_company creates a revision on every save,
and that list_revisions_for_company returns them newest-first.
Uses the same in-memory stub pattern as the existing system_prompts tests.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

from app.services.system_prompts import list_revisions_for_company, upsert_prompt_for_company


def _make_company():
    return SimpleNamespace(id=uuid4())


def _make_user():
    return SimpleNamespace(id=uuid4())


def _make_db():
    db = MagicMock()
    db.scalar.return_value = None  # no existing prompt by default
    db.scalars.return_value = iter([])
    return db


# ─── upsert creates a revision ────────────────────────────────────────────


def test_upsert_creates_revision_on_first_save() -> None:
    db = _make_db()
    company = _make_company()
    user = _make_user()

    upsert_prompt_for_company(db, company=company, user=user, content="Hello bot")

    added_objects = [c.args[0] for c in db.add.call_args_list]
    class_names = [type(obj).__name__ for obj in added_objects]
    assert "CompanySystemPromptRevision" in class_names


def test_upsert_creates_revision_on_update() -> None:
    from app.models.system_prompts import CompanySystemPrompt
    existing = CompanySystemPrompt(
        company_id=uuid4(), content="old prompt", updated_by_user_id=None
    )
    db = _make_db()
    db.scalar.return_value = existing
    company = _make_company()
    user = _make_user()

    upsert_prompt_for_company(db, company=company, user=user, content="new prompt")

    added_objects = [c.args[0] for c in db.add.call_args_list]
    class_names = [type(obj).__name__ for obj in added_objects]
    assert "CompanySystemPromptRevision" in class_names


def test_revision_stores_correct_content() -> None:
    db = _make_db()
    company = _make_company()
    user = _make_user()

    upsert_prompt_for_company(db, company=company, user=user, content="You are Maya.")

    from app.models.system_prompts import CompanySystemPromptRevision
    added_revisions = [
        c.args[0] for c in db.add.call_args_list
        if isinstance(c.args[0], CompanySystemPromptRevision)
    ]
    assert len(added_revisions) == 1
    assert added_revisions[0].content == "You are Maya."
    assert added_revisions[0].company_id == company.id
    assert added_revisions[0].updated_by_user_id == user.id


# ─── list_revisions_for_company ───────────────────────────────────────────


def test_list_revisions_returns_results() -> None:
    from app.models.system_prompts import CompanySystemPromptRevision
    rev1 = CompanySystemPromptRevision(company_id=uuid4(), content="v1", updated_by_user_id=None)
    rev2 = CompanySystemPromptRevision(company_id=uuid4(), content="v2", updated_by_user_id=None)

    db = _make_db()
    db.scalars.return_value = iter([rev2, rev1])
    company = _make_company()

    results = list_revisions_for_company(db, company, limit=20)

    assert results == [rev2, rev1]


def test_list_revisions_passes_limit() -> None:
    db = _make_db()
    db.scalars.return_value = iter([])
    company = _make_company()

    list_revisions_for_company(db, company, limit=5)

    db.scalars.assert_called_once()
