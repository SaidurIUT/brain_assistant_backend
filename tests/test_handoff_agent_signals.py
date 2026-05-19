"""
Tests for the agent-side handoff signalling (US-06 T2/T3/T4/T5).

Covers the private-note builder (template fallback + LLM summary path) and
the orchestrator that fires status flip, private note, and label tagging.
No real Chatwoot calls — side-effect functions are passed in as mocks.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.rag_service import QueryResult, summarise_for_handoff
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


# ─── _build_handoff_note — template fallback (summary="") ─────────────────


def test_note_falls_back_to_template_when_no_summary() -> None:
    note = _build_handoff_note(
        summary="",
        customer_message="how do refunds work?",
        chunk_count=0,
        threshold=0.3,
    )
    assert "how do refunds work?" in note
    assert "0 chunk" in note
    assert "0.3" in note
    assert "low confidence" in note.lower()


def test_note_trims_very_long_customer_messages() -> None:
    note = _build_handoff_note(
        summary="",
        customer_message="x" * 1000,
        chunk_count=0,
        threshold=0.3,
    )
    assert len(note) < 800
    assert "…" in note


def test_note_handles_empty_customer_message_gracefully() -> None:
    note = _build_handoff_note(
        summary="",
        customer_message="",
        chunk_count=0,
        threshold=0.3,
    )
    assert "(empty message)" in note


# ─── _build_handoff_note — LLM summary path (T5) ──────────────────────────


def test_note_uses_llm_summary_when_provided() -> None:
    summary = "The customer is asking about the return policy for a broken item."
    note = _build_handoff_note(
        summary=summary,
        customer_message="how do refunds work?",
        chunk_count=0,
        threshold=0.3,
    )
    assert summary in note
    assert "🤖 Bot handed off" in note
    assert "Please take it from here." in note


def test_note_does_not_include_template_debug_info_when_summary_present() -> None:
    note = _build_handoff_note(
        summary="The customer wants help with their invoice.",
        customer_message="show me my invoice",
        chunk_count=0,
        threshold=0.3,
    )
    # Template debug lines should NOT appear when a summary is provided
    assert "chunk(s)" not in note
    assert "cosine" not in note


def test_note_whitespace_only_summary_falls_back_to_template() -> None:
    note = _build_handoff_note(
        summary="   ",
        customer_message="what time does support close?",
        chunk_count=1,
        threshold=0.3,
    )
    assert "what time does support close?" in note
    assert "1 chunk" in note


# ─── summarise_for_handoff (T5) ───────────────────────────────────────────


def test_summarise_for_handoff_calls_llm_with_formatted_conversation() -> None:
    import asyncio

    history = [
        {"sender": "contact", "content": "My order arrived broken."},
        {"sender": "bot", "content": "I'm sorry to hear that."},
    ]
    with patch(
        "app.services.rag_service._llm_complete",
        new=AsyncMock(return_value="The customer received a broken order."),
    ) as mock_llm:
        result = asyncio.run(summarise_for_handoff(history, "Can I get a refund?"))

    assert result == "The customer received a broken order."
    prompt_text = mock_llm.call_args.args[0]
    assert "Customer: My order arrived broken." in prompt_text
    assert "Assistant: I'm sorry to hear that." in prompt_text
    assert "Customer: Can I get a refund?" in prompt_text


def test_summarise_for_handoff_returns_empty_string_on_llm_failure() -> None:
    import asyncio

    with patch(
        "app.services.rag_service._llm_complete",
        new=AsyncMock(side_effect=Exception("LLM timeout")),
    ):
        result = asyncio.run(summarise_for_handoff([], "any message"))

    assert result == ""


def test_summarise_for_handoff_returns_empty_string_when_llm_returns_none() -> None:
    import asyncio

    with patch(
        "app.services.rag_service._llm_complete",
        new=AsyncMock(return_value=None),
    ):
        result = asyncio.run(summarise_for_handoff([], "any message"))

    assert result == ""


# ─── _signal_handoff_to_agent ─────────────────────────────────────────────


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
        handoff_summary="",
        set_status=set_status,
        send_note=send_note,
        add_labels=add_labels,
    )

    # T2 — conversation flipped to 'open'
    set_status.assert_called_once()
    assert set_status.call_args.kwargs["status"] == "open"
    assert set_status.call_args.kwargs["conversation_display_id"] == 42

    # T3 — private note posted
    send_note.assert_called_once()
    sent_content = send_note.call_args.kwargs["content"]
    assert event.content in sent_content
    assert "low confidence" in sent_content.lower()
    assert send_note.call_args.kwargs["agent_bot_id"] == 2

    # T4 — low_confidence label added
    add_labels.assert_called_once()
    assert add_labels.call_args.kwargs["labels"] == [_HANDOFF_LABEL_LOW_CONFIDENCE]


def test_handoff_signals_include_llm_summary_in_note() -> None:
    event = _make_event()
    connection = _make_connection()
    query_result = QueryResult(answer=None, confident=False, chunk_count=0)
    summary = "The customer is asking about their missing shipment."

    send_note = MagicMock()

    _signal_handoff_to_agent(
        connection=connection,
        event=event,
        query_result=query_result,
        handoff_summary=summary,
        set_status=MagicMock(),
        send_note=send_note,
        add_labels=MagicMock(),
    )

    sent_content = send_note.call_args.kwargs["content"]
    assert summary in sent_content


def test_handoff_signals_use_connection_credentials() -> None:
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
        handoff_summary="",
        set_status=set_status,
        send_note=send_note,
        add_labels=add_labels,
    )

    for mock in (set_status, send_note, add_labels):
        kwargs = mock.call_args.kwargs
        assert kwargs["base_url"] == connection["base_url"]
        assert kwargs["account_id"] == connection["account_id"]
        assert kwargs["agent_bot_token"] == connection["agent_bot_token"]
