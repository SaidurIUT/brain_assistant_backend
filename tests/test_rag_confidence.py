"""
Unit tests for the retrieval-confidence helper (US-06 T1).

Covers _evaluate_retrieval — the pure function that decides how many chunks
LightRAG's aquery_data actually returned. Avoids spinning up LightRAG itself.
"""

from app.services.rag_service import _evaluate_retrieval


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
