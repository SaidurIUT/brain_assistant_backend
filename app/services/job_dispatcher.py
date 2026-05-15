from uuid import UUID

from sqlalchemy.orm import Session

from app.core.datetime import utc_now
from app.models import BackgroundJob, KnowledgeDocument, WebsiteCrawlJob
from app.services import rag_service
from app.services.crawl_discovery import run_website_crawl_discovery
from app.services.document_extraction import DocumentExtractionError, extract_document_text
from app.services.jobs import (
    DOCUMENT_TEXT_EXTRACTION,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_INGESTING,
    JOB_PROCESSING,
    SINGLE_PAGE_WEB_SCRAPE,
    WEBSITE_CRAWL_DISCOVERY,
)
from app.services.web_scraper import WebScrapeError, scrape_single_page


def dispatch_background_job(db: Session, job_id: UUID) -> BackgroundJob | None:
    job = db.get(BackgroundJob, job_id)
    if job is None:
        return None
    if job.status == JOB_COMPLETED:
        return job

    job.status = JOB_PROCESSING
    job.started_at = utc_now()
    job.attempt_count += 1
    job.error_message = ""
    db.flush()

    try:
        handler = JOB_HANDLERS[job.job_type]
    except KeyError:
        fail_job(db, job, f"Unknown background job type: {job.job_type}")
        return job

    try:
        handler(db, job)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        fail_job(db, job, message[:1000])

    return job


def handle_document_text_extraction(db: Session, job: BackgroundJob) -> None:
    knowledge_document_id = job.payload.get("knowledge_document_id")
    if not knowledge_document_id:
        raise DocumentExtractionError("Missing knowledge document id")

    knowledge_document = db.get(KnowledgeDocument, UUID(str(knowledge_document_id)))
    if knowledge_document is None:
        raise DocumentExtractionError("Knowledge document not found")

    knowledge_document.status = JOB_PROCESSING
    knowledge_document.started_at = job.started_at or utc_now()
    knowledge_document.error_message = ""
    db.flush()

    result = extract_document_text(
        str(job.payload.get("storage_path") or ""),
        str(job.payload.get("original_filename") or ""),
    )

    knowledge_document.extracted_text = result.text
    knowledge_document.char_count = len(result.text)
    knowledge_document.document_metadata = result.metadata
    knowledge_document.error_message = ""
    knowledge_document.status = JOB_INGESTING
    db.flush()

    if result.text.strip():
        rag_service.sync_ingest(result.text)

    now = utc_now()
    knowledge_document.status = JOB_COMPLETED
    knowledge_document.completed_at = now

    job.status = JOB_COMPLETED
    job.completed_at = now
    job.error_message = ""
    job.result = {
        "knowledge_document_id": str(knowledge_document.id),
        "char_count": knowledge_document.char_count,
        "metadata": result.metadata,
    }
    db.flush()


def handle_single_page_web_scrape(db: Session, job: BackgroundJob) -> None:
    knowledge_document_id = job.payload.get("knowledge_document_id")
    if not knowledge_document_id:
        raise WebScrapeError("Missing knowledge document id")

    knowledge_document = db.get(KnowledgeDocument, UUID(str(knowledge_document_id)))
    if knowledge_document is None:
        raise WebScrapeError("Knowledge document not found")

    knowledge_document.status = JOB_PROCESSING
    knowledge_document.started_at = job.started_at or utc_now()
    knowledge_document.error_message = ""
    db.flush()

    result = scrape_single_page(
        str(job.payload.get("url") or ""),
        int(job.payload.get("wait_seconds") or 2),
    )

    now = utc_now()
    knowledge_document.status = JOB_COMPLETED
    knowledge_document.source_title = result.title[:500]
    knowledge_document.source_url = result.final_url
    knowledge_document.extracted_text = result.text
    knowledge_document.char_count = len(result.text)
    knowledge_document.document_metadata = result.metadata
    knowledge_document.completed_at = now
    knowledge_document.error_message = ""

    job.status = JOB_COMPLETED
    job.completed_at = now
    job.error_message = ""
    job.result = {
        "knowledge_document_id": str(knowledge_document.id),
        "char_count": knowledge_document.char_count,
        "metadata": result.metadata,
    }
    db.flush()


def handle_website_crawl_discovery(db: Session, job: BackgroundJob) -> None:
    crawl_job_id = job.payload.get("crawl_job_id")
    if not crawl_job_id:
        raise ValueError("Missing website crawl job id")

    crawl_job = db.get(WebsiteCrawlJob, UUID(str(crawl_job_id)))
    if crawl_job is None:
        raise ValueError("Website crawl job not found")

    run_website_crawl_discovery(db, crawl_job)
    if crawl_job.status == JOB_FAILED:
        fail_job(db, job, crawl_job.error_message or "Website crawl discovery failed")
        return

    now = utc_now()
    job.status = JOB_COMPLETED
    job.completed_at = now
    job.error_message = ""
    job.result = {
        "crawl_job_id": str(crawl_job.id),
        "total_discovered": crawl_job.total_discovered,
        "total_matched": crawl_job.total_matched,
    }
    db.flush()


def fail_job(db: Session, job: BackgroundJob, message: str) -> None:
    now = utc_now()
    job.status = JOB_FAILED
    job.error_message = message
    job.completed_at = now

    if job.job_type in {DOCUMENT_TEXT_EXTRACTION, SINGLE_PAGE_WEB_SCRAPE}:
        knowledge_document_id = job.payload.get("knowledge_document_id")
        if knowledge_document_id:
            knowledge_document = db.get(KnowledgeDocument, UUID(str(knowledge_document_id)))
        elif job.knowledge_documents:
            knowledge_document = job.knowledge_documents[0]
        else:
            knowledge_document = None
        if knowledge_document is not None:
            knowledge_document.status = JOB_FAILED
            knowledge_document.error_message = message
            knowledge_document.completed_at = now
    elif job.job_type == WEBSITE_CRAWL_DISCOVERY:
        crawl_job_id = job.payload.get("crawl_job_id")
        crawl_job = db.get(WebsiteCrawlJob, UUID(str(crawl_job_id))) if crawl_job_id else None
        if crawl_job is not None:
            crawl_job.status = JOB_FAILED
            crawl_job.error_message = message
            crawl_job.completed_at = now


JOB_HANDLERS = {
    DOCUMENT_TEXT_EXTRACTION: handle_document_text_extraction,
    SINGLE_PAGE_WEB_SCRAPE: handle_single_page_web_scrape,
    WEBSITE_CRAWL_DISCOVERY: handle_website_crawl_discovery,
}
