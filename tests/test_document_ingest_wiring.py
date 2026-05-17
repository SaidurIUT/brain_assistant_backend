"""
Smoke tests for the upload → extract → ingest pipeline wiring (US-08 T4).

These don't touch the DB — they stub the Session, the extractor, and
rag_service.sync_ingest, then assert the dispatcher composes them correctly:
extracted text is handed to LightRAG, document status reflects the phase,
and ingest failures surface through the existing fail_job path.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services import job_dispatcher
from app.services.document_extraction import DocumentExtractionResult
from app.services.jobs import JOB_COMPLETED, JOB_FAILED, JOB_INGESTING, JOB_PROCESSING


def _make_job_and_doc():
    doc_id = uuid4()
    company_id = uuid4()
    knowledge_document = SimpleNamespace(
        id=doc_id,
        company_id=company_id,
        status=JOB_PROCESSING,
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
            "storage_path": "/tmp/fake.pdf",
            "original_filename": "fake.pdf",
        },
        knowledge_documents=[],
    )
    return job, knowledge_document


def test_extraction_feeds_text_into_rag_ingest() -> None:
    job, doc = _make_job_and_doc()
    db = MagicMock()
    db.get.return_value = doc

    extract = patch.object(
        job_dispatcher,
        "extract_document_text",
        return_value=DocumentExtractionResult(
            text="Brain Assistant supports uploads.",
            metadata={"extension": ".pdf"},
        ),
    )
    ingest = patch("app.services.rag_service.sync_ingest")

    with extract, ingest as mock_ingest:
        job_dispatcher.handle_document_text_extraction(db, job)

    mock_ingest.assert_called_once_with("Brain Assistant supports uploads.", doc.company_id)
    assert doc.extracted_text == "Brain Assistant supports uploads."
    assert doc.status == JOB_COMPLETED
    assert job.status == JOB_COMPLETED
    assert doc.completed_at is not None


def test_empty_extracted_text_skips_ingest_but_completes() -> None:
    """Scanned PDFs with no OCR yield empty text; we shouldn't call ingest with that."""
    job, doc = _make_job_and_doc()
    db = MagicMock()
    db.get.return_value = doc

    extract = patch.object(
        job_dispatcher,
        "extract_document_text",
        return_value=DocumentExtractionResult(text="   ", metadata={"extension": ".pdf"}),
    )
    ingest = patch("app.services.rag_service.sync_ingest")

    with extract, ingest as mock_ingest:
        job_dispatcher.handle_document_text_extraction(db, job)

    mock_ingest.assert_not_called()
    assert doc.status == JOB_COMPLETED
    assert job.status == JOB_COMPLETED


def test_ingest_failure_propagates_to_outer_dispatcher() -> None:
    """The handler doesn't catch ingest errors; dispatch_background_job's outer
    try/except must mark both the job and the document as failed via fail_job."""
    job, doc = _make_job_and_doc()
    job.id = uuid4()
    job.job_type = "document_text_extraction"

    db = MagicMock()
    # dispatch_background_job calls db.get(BackgroundJob, ...) first, then the
    # handler calls db.get(KnowledgeDocument, ...). Same mock works for both.
    db.get.return_value = job

    extract = patch.object(
        job_dispatcher,
        "extract_document_text",
        return_value=DocumentExtractionResult(text="some text", metadata={}),
    )
    ingest = patch(
        "app.services.rag_service.sync_ingest",
        side_effect=RuntimeError("ollama unreachable"),
    )

    def db_get(model, _id):
        return doc if model.__name__ == "KnowledgeDocument" else job

    db.get.side_effect = db_get

    with extract, ingest:
        job_dispatcher.dispatch_background_job(db, job.id)

    assert job.status == JOB_FAILED
    assert "ollama unreachable" in job.error_message
    assert doc.status == JOB_FAILED
    assert doc.error_message == job.error_message


def test_status_transitions_through_ingesting() -> None:
    """Before ingest runs, status should be JOB_INGESTING so the UI can show progress."""
    job, doc = _make_job_and_doc()
    db = MagicMock()
    db.get.return_value = doc

    observed_status_at_ingest_time = []

    def capture_status(_text: str, _company_id) -> None:
        observed_status_at_ingest_time.append(doc.status)

    extract = patch.object(
        job_dispatcher,
        "extract_document_text",
        return_value=DocumentExtractionResult(text="hello", metadata={}),
    )
    ingest = patch("app.services.rag_service.sync_ingest", side_effect=capture_status)

    with extract, ingest:
        job_dispatcher.handle_document_text_extraction(db, job)

    assert observed_status_at_ingest_time == [JOB_INGESTING]
    assert doc.status == JOB_COMPLETED
