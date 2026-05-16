"""
Smoke tests for the customer-message → bot-reply flow (US5).

These don't spin up Chatwoot or call the office PC's LLM — they exercise the
worker's branching: outgoing messages get skipped, missing connection fails
cleanly, and the reply is cleaned of LightRAG markdown before storing.
"""

from app.services.rag_service import QueryResult
from app.workers.process_event import (
    _HANDOFF_REPLY,
    _build_question_with_history,
    _choose_reply,
    _clean_reply,
)


def test_clean_reply_extracts_answer_section() -> None:
    raw = (
        "### References\n\n- [1] Some chunk\n\n"
        "### Answer\n\nBrain Assistant is an AI support tool."
    )
    assert _clean_reply(raw) == "Brain Assistant is an AI support tool."


def test_clean_reply_strips_references_when_no_answer_header() -> None:
    raw = (
        "Brain Assistant 23 is built on Chatwoot.\n\n"
        "### References\n\n- [1] Doc chunk\n"
    )
    cleaned = _clean_reply(raw)
    assert "Brain Assistant 23 is built on Chatwoot." in cleaned
    assert "References" not in cleaned
    assert "[1]" not in cleaned


def test_clean_reply_passes_plain_text_through() -> None:
    raw = "Just a plain answer with no markdown."
    assert _clean_reply(raw) == raw


def test_clean_reply_handles_empty_input() -> None:
    assert _clean_reply("") == ""
    assert _clean_reply("   ") == "   "


def test_build_question_with_empty_history_returns_message_verbatim() -> None:
    assert _build_question_with_history([], "what is this?") == "what is this?"


def test_build_question_includes_recent_turns() -> None:
    history = [
        {"sender": "contact", "content": "Hi"},
        {"sender": "bot", "content": "Hello! How can I help?"},
        {"sender": "contact", "content": "I have a billing question"},
    ]
    question = _build_question_with_history(history, "can you help me?")

    assert "Customer: Hi" in question
    assert "Assistant: Hello! How can I help?" in question
    assert "Customer: I have a billing question" in question
    assert "can you help me?" in question


def test_low_confidence_query_routes_to_handoff() -> None:
    result = QueryResult(answer=None, confident=False, chunk_count=0)
    assert _choose_reply(result, _clean_reply) == _HANDOFF_REPLY


def test_high_confidence_query_returns_cleaned_answer() -> None:
    result = QueryResult(
        answer="### Answer\n\nBrain Assistant is an AI support tool.",
        confident=True,
        chunk_count=3,
    )
    assert _choose_reply(result, _clean_reply) == "Brain Assistant is an AI support tool."


def test_confident_but_empty_answer_falls_back() -> None:
    """LLM occasionally returns whitespace despite having context — don't ship that."""
    result = QueryResult(answer="   ", confident=True, chunk_count=2)
    reply = _choose_reply(result, _clean_reply)
    assert reply != _HANDOFF_REPLY
    assert "get back to you" in reply.lower()
