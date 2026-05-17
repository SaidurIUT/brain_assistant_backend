"""
Tests for the agent-side handoff signalling (US-06 T2/T3/T4).

Covers the pure helper that renders the private-note text and the
orchestrator that fires off status flip, private note, and label tagging
when the bot hands off. No real Chatwoot calls — the three side-effect
functions are passed in as mocks so we can assert exactly what'd be sent.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.rag_service import QueryResult
from app.workers.process_event import (
    _HANDOFF_LABEL_LOW_CONFIDENCE,
    _build_handoff_note,
    _signal_handoff_to_agent,
)


def _make_event(content="What's the weather in Tokyo?", display_id=42):
    return SimpleNamespace(content=content, conversation_display_id=display_id)


def _make_connection():
    return {
        "company_id": "fake-uuid",
        "base_url": "http://chatwoot.local:3000",
        "account_id": 1,
        "agent_bot_id": 2,
        "agent_bot_token": "secret-token",
    }


# ─── _build_handoff_note ───────────────────────────────────────────


def test_note_includes_customer_message_and_chunk_count() -> None:
    note = _build_handoff_note(
        customer_message="how do refunds work?",
        chunk_count=0,
        threshold=0.3,
    )
    assert "how do refunds work?" in note
    assert "0 chunk" in note
    assert "0.3" in note
    assert "low confidence" in note.lower()


def test_note_trims_very_long_customer_messages() -> None:
    long_message = "x" * 1000
    note = _build_handoff_note(
        customer_message=long_message,
        chunk_count=0,
        threshold=0.3,
    )
    # Should be truncated with ellipsis, not include all 1000 chars
    assert len(note) < 800
    assert "…" in note


def test_note_handles_empty_customer_message_gracefully() -> None:
    note = _build_handoff_note(
        customer_message="",
        chunk_count=0,
        threshold=0.3,
    )
    assert "(empty message)" in note


# ─── _signal_handoff_to_agent ──────────────────────────────────────


def test_handoff_signals_fire_status_note_and_label() -> None:
    event = _make_event()
    connection = _make_connection()
    query_result = QueryResult(answer=None, confident=False, chunk_count=0)

    set_status = MagicMock()
    send_note = MagicMock()
    add_labels = MagicMock()

    _signal_handoff_to_agent(
        connection=connection,
        event=event,
        query_result=query_result,
        set_status=set_status,
        send_note=send_note,
        add_labels=add_labels,
    )

    # T2 — conversation flipped to 'open'
    set_status.assert_called_once()
    assert set_status.call_args.kwargs["status"] == "open"
    assert set_status.call_args.kwargs["conversation_display_id"] == 42

    # T3 — private note with rendered context
    send_note.assert_called_once()
    sent_content = send_note.call_args.kwargs["content"]
    assert event.content in sent_content
    assert "low confidence" in sent_content.lower()
    assert send_note.call_args.kwargs["agent_bot_id"] == 2  # passed through

    # T4 — low_confidence label added
    add_labels.assert_called_once()
    assert add_labels.call_args.kwargs["labels"] == [_HANDOFF_LABEL_LOW_CONFIDENCE]


def test_handoff_signals_use_connection_credentials() -> None:
    """All three calls share the same Chatwoot credentials from `connection`."""
    event = _make_event()
    connection = _make_connection()
    query_result = QueryResult(answer=None, confident=False, chunk_count=0)

    set_status = MagicMock()
    send_note = MagicMock()
    add_labels = MagicMock()

    _signal_handoff_to_agent(
        connection=connection,
        event=event,
        query_result=query_result,
        set_status=set_status,
        send_note=send_note,
        add_labels=add_labels,
    )

    for mock in (set_status, send_note, add_labels):
        kwargs = mock.call_args.kwargs
        assert kwargs["base_url"] == connection["base_url"]
        assert kwargs["account_id"] == connection["account_id"]
        assert kwargs["agent_bot_token"] == connection["agent_bot_token"]
