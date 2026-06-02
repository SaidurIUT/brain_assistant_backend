"""
Unit tests for the retrieval-confidence helper (US-06 T1).

Covers _evaluate_retrieval — the pure function that decides how many chunks
LightRAG's aquery_data actually returned. Avoids spinning up LightRAG itself.
"""

from app.services.rag_service import _evaluate_retrieval, _is_insufficient_answer


def test_counts_chunks_from_success_response() -> None:
    data = {
        "status": "success",
        "data": {
            "chunks": [
                {"chunk_id": "a", "content": "..."},
                {"chunk_id": "b", "content": "..."},
                {"chunk_id": "c", "content": "..."},
            ],
        },
    }
    assert _evaluate_retrieval(data) == 3


def test_returns_zero_when_no_chunks_pass_threshold() -> None:
    data = {"status": "success", "data": {"chunks": []}}
    assert _evaluate_retrieval(data) == 0


def test_returns_zero_on_failure_status() -> None:
    """LightRAG flags empty keyword extraction etc. as status=failure."""
    data = {"status": "failure", "message": "No keywords extracted", "data": {}}
    assert _evaluate_retrieval(data) == 0


def test_returns_zero_on_none() -> None:
    assert _evaluate_retrieval(None) == 0


def test_returns_zero_when_chunks_key_missing() -> None:
    data = {"status": "success", "data": {}}
    assert _evaluate_retrieval(data) == 0


def test_returns_zero_when_chunks_is_none() -> None:
    data = {"status": "success", "data": {"chunks": None}}
    assert _evaluate_retrieval(data) == 0


# ─── _is_insufficient_answer ──────────────────────────────────────────────


def test_detects_dont_have_enough_information() -> None:
    assert _is_insufficient_answer("I don't have enough information to answer that.")


def test_detects_no_relevant_information() -> None:
    assert _is_insufficient_answer("There is no relevant information in the context.")


def test_detects_cannot_find() -> None:
    assert _is_insufficient_answer("I cannot find an answer to your question.")


def test_detects_unable_to_answer() -> None:
    assert _is_insufficient_answer("I'm unable to answer based on the provided context.")


def test_real_answer_not_flagged() -> None:
    answer = (
        "Our return policy allows returns within 30 days. "
        "You can initiate a return from your account dashboard. "
        "Refunds are processed within 5-7 business days."
    )
    assert not _is_insufficient_answer(answer)


def test_detects_lightrag_no_context_marker() -> None:
    answer = "Sorry, I'm not able to provide an answer to that question.[no-context]"
    assert _is_insufficient_answer(answer)


def test_detects_not_able_to_provide() -> None:
    assert _is_insufficient_answer("I'm not able to provide an answer to that.")


def test_detects_dont_have_any_information() -> None:
    assert _is_insufficient_answer("I don't have any information about that.")


def test_no_context_marker_ignores_length_guard() -> None:
    long_answer = ("filler text " * 50) + "[no-context]"
    assert _is_insufficient_answer(long_answer)


def test_long_answer_mentioning_gap_not_flagged() -> None:
    # A real answer that happens to mention a gap mid-sentence should not trigger
    answer = (
        "We offer free shipping on orders over $50. "
        "For international orders we don't have enough coverage yet, "
        "but domestic orders are fully supported. "
        "You can track your order from the dashboard. "
        "Returns are accepted within 30 days of delivery. "
        "Contact support for any issues."
    )
    assert not _is_insufficient_answer(answer)
