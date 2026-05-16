"""
Smoke tests for the web-scrape → ingest pipeline wiring (US-07 T3).

Mirror of test_document_ingest_wiring.py — same dispatcher, different content
source (Playwright scrape instead of file extraction). These tests don't touch
the DB; they stub the Session, the scraper, and rag_service.sync_ingest, then
assert the dispatcher composes them correctly: scraped text reaches LightRAG,
document status reflects the phase, ingest failures surface via fail_job.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services import job_dispatcher
from app.services.jobs import JOB_COMPLETED, JOB_FAILED, JOB_INGESTING, JOB_PROCESSING
from app.services.web_scraper import WebScrapeResult


def _make_job_and_doc():
    doc_id = uuid4()
    knowledge_document = SimpleNamespace(
        id=doc_id,
        status=JOB_PROCESSING,
        source_title="",
        source_url="",
        extracted_text="",
        char_count=0,
        document_metadata={},
        error_message="",
        completed_at=None,
    )
    job = SimpleNamespace(
        status=JOB_PROCESSING,
        started_at=None,
        completed_at=None,
        attempt_count=0,
        error_message="",
        result=None,
        payload={
            "knowledge_document_id": str(doc_id),
            "url": "https://example.com/faq",
            "wait_seconds": 2,
        },
        knowledge_documents=[],
    )
    return job, knowledge_document


def _scrape_result(text: str = "Our refund policy lasts 30 days.") -> WebScrapeResult:
    return WebScrapeResult(
        text=text,
        metadata={"extractor": "playwright", "url": "https://example.com/faq"},
        title="FAQ — Example",
        final_url="https://example.com/faq",
    )


def test_scrape_feeds_text_into_rag_ingest() -> None:
    job, doc = _make_job_and_doc()
    db = MagicMock()
    db.get.return_value = doc

    scrape = patch.object(job_dispatcher, "scrape_single_page", return_value=_scrape_result())
    ingest = patch("app.services.rag_service.sync_ingest")

    with scrape, ingest as mock_ingest:
        job_dispatcher.handle_single_page_web_scrape(db, job)

    mock_ingest.assert_called_once_with("Our refund policy lasts 30 days.")
    assert doc.extracted_text == "Our refund policy lasts 30 days."
    assert doc.source_url == "https://example.com/faq"
    assert doc.status == JOB_COMPLETED
    assert job.status == JOB_COMPLETED
    assert doc.completed_at is not None


def test_empty_scraped_text_skips_ingest_but_completes() -> None:
    """Pages that render no readable text (login walls, empty SPAs) shouldn't
    poison the index with empty embeddings — skip ingest, mark completed."""
    job, doc = _make_job_and_doc()
    db = MagicMock()
    db.get.return_value = doc

    scrape = patch.object(job_dispatcher, "scrape_single_page", return_value=_scrape_result(text="   "))
    ingest = patch("app.services.rag_service.sync_ingest")

    with scrape, ingest as mock_ingest:
        job_dispatcher.handle_single_page_web_scrape(db, job)

    mock_ingest.assert_not_called()
    assert doc.status == JOB_COMPLETED
    assert job.status == JOB_COMPLETED


def test_ingest_failure_propagates_to_outer_dispatcher() -> None:
    """Ingest errors must mark both the job and the document failed via the
    existing fail_job path. The scraped text stays on the doc so a retry
    doesn't need to re-fetch the page."""
    job, doc = _make_job_and_doc()
    job.id = uuid4()
    job.job_type = "single_page_web_scrape"

    db = MagicMock()

    def db_get(model, _id):
        return doc if model.__name__ == "KnowledgeDocument" else job

    db.get.side_effect = db_get

    scrape = patch.object(job_dispatcher, "scrape_single_page", return_value=_scrape_result())
    ingest = patch(
        "app.services.rag_service.sync_ingest",
        side_effect=RuntimeError("ollama unreachable"),
    )

    with scrape, ingest:
        job_dispatcher.dispatch_background_job(db, job.id)

    assert job.status == JOB_FAILED
    assert "ollama unreachable" in job.error_message
    assert doc.status == JOB_FAILED
    assert doc.error_message == job.error_message
    # Scrape work is preserved for retry
    assert doc.extracted_text == "Our refund policy lasts 30 days."


def test_status_transitions_through_ingesting() -> None:
    """Before ingest runs, status should be JOB_INGESTING so the UI can show
    progress between 'scraping done' and 'ready for the bot'."""
    job, doc = _make_job_and_doc()
    db = MagicMock()
    db.get.return_value = doc

    observed_status_at_ingest_time = []

    def capture_status(_text: str) -> None:
        observed_status_at_ingest_time.append(doc.status)

    scrape = patch.object(job_dispatcher, "scrape_single_page", return_value=_scrape_result())
    ingest = patch("app.services.rag_service.sync_ingest", side_effect=capture_status)

    with scrape, ingest:
        job_dispatcher.handle_single_page_web_scrape(db, job)

    assert observed_status_at_ingest_time == [JOB_INGESTING]
    assert doc.status == JOB_COMPLETED
