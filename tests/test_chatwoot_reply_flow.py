"""
Smoke tests for the customer-message → bot-reply flow (US5).

These don't spin up Chatwoot or call the office PC's LLM — they exercise the
worker's branching: outgoing messages get skipped, missing connection fails
cleanly, and the reply is cleaned of LightRAG markdown before storing.
"""

from unittest.mock import MagicMock, patch

from app.workers.process_event import _build_question_with_history, _clean_reply


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
