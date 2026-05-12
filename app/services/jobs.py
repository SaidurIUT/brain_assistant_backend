from uuid import UUID

from sqlalchemy.orm import Session

from app.core.datetime import utc_now
from app.models.auth import BackgroundJob, Company, CompanyUpload, KnowledgeDocument

DOCUMENT_TEXT_EXTRACTION = "document_text_extraction"
SINGLE_PAGE_WEB_SCRAPE = "single_page_web_scrape"
JOB_QUEUED = "queued"
JOB_PROCESSING = "processing"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"


def create_document_extraction_job(
    db: Session,
    *,
    upload: CompanyUpload,
    priority: int = 0,
) -> tuple[KnowledgeDocument, BackgroundJob]:
    now = utc_now()
    knowledge_document = KnowledgeDocument(
        company_id=upload.company_id,
        upload_id=upload.id,
        source_type="upload",
        source_title=upload.original_filename,
        status=JOB_QUEUED,
        queued_at=now,
    )
    db.add(knowledge_document)
    db.flush()

    background_job = BackgroundJob(
        company_id=upload.company_id,
        job_type=DOCUMENT_TEXT_EXTRACTION,
        status=JOB_QUEUED,
        priority=priority,
        payload={
            "upload_id": str(upload.id),
            "knowledge_document_id": str(knowledge_document.id),
            "storage_path": upload.storage_path,
            "original_filename": upload.original_filename,
            "content_type": upload.content_type,
        },
        queued_at=now,
    )
    db.add(background_job)
    db.flush()

    knowledge_document.current_job_id = background_job.id
    db.flush()
    return knowledge_document, background_job


def create_single_page_web_scrape_job(
    db: Session,
    *,
    company: Company,
    url: str,
    wait_seconds: int = 2,
    priority: int = 0,
) -> tuple[KnowledgeDocument, BackgroundJob]:
    now = utc_now()
    knowledge_document = KnowledgeDocument(
        company_id=company.id,
        source_type="web_page",
        source_url=url,
        source_title=url,
        status=JOB_QUEUED,
        queued_at=now,
    )
    db.add(knowledge_document)
    db.flush()

    background_job = BackgroundJob(
        company_id=company.id,
        job_type=SINGLE_PAGE_WEB_SCRAPE,
        status=JOB_QUEUED,
        priority=priority,
        payload={
            "knowledge_document_id": str(knowledge_document.id),
            "url": url,
            "wait_seconds": wait_seconds,
        },
        queued_at=now,
    )
    db.add(background_job)
    db.flush()

    knowledge_document.current_job_id = background_job.id
    db.flush()
    return knowledge_document, background_job


def enqueue_background_job(job_id: UUID):
    from app.jobs.tasks import process_background_job

    return process_background_job.delay(str(job_id))


def mark_job_failed(db: Session, job: BackgroundJob, knowledge_document: KnowledgeDocument, message: str) -> None:
    now = utc_now()
    job.status = JOB_FAILED
    job.error_message = message
    job.completed_at = now
    knowledge_document.status = JOB_FAILED
    knowledge_document.error_message = message
    knowledge_document.completed_at = now
    db.flush()
