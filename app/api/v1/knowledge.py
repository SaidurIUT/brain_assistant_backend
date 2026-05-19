from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.core.datetime import utc_now
from app.models import KnowledgeDocument, User, WebsiteCrawlCandidate, WebsiteCrawlJob
from app.schemas.auth import MessageResponse
from app.schemas.knowledge import (
    CrawlCategoryPublic,
    KnowledgeExtractionPublic,
    KnowledgeExtractionUpdateRequest,
    KnowledgeSourcePublic,
    WebPageScrapeRequest,
    WebsiteCrawlCandidatePublic,
    WebsiteCrawlCreateRequest,
    WebsiteCrawlJobDetailPublic,
    WebsiteCrawlJobPublic,
    WebsiteCrawlQueueRequest,
    WebsiteCrawlScheduleRequest,
)
from app.services.crawl_discovery import (
    category_options,
    crawl_job_for_company,
    list_crawl_jobs,
    normalize_url,
)
from app.services import rag_service
from app.services.auth import audit_event
from app.services.jobs import (
    SINGLE_PAGE_WEB_SCRAPE,
    create_single_page_web_scrape_job,
    create_website_crawl_discovery_job,
    enqueue_background_job,
    enqueue_stale_queued_jobs,
    mark_job_failed,
)
from app.services.settings import current_company, require_company_admin

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class IngestRequest(BaseModel):
    content: str


@router.post("/ingest", status_code=202)
async def ingest_document(
    payload: IngestRequest,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ingest a text document into the caller's tenant knowledge base."""
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    company = current_company(db, current_user, company_id)
    await rag_service.ingest(payload.content, company.id)
    return {"message": "Document ingested successfully"}


def knowledge_source_public(record: KnowledgeDocument) -> KnowledgeSourcePublic:
    return KnowledgeSourcePublic.model_validate(
        {
            **record.__dict__,
            "source_title": record.source_title or record.source_url,
            "error_message": record.error_message,
        }
    )


def knowledge_extraction_public(record: KnowledgeDocument) -> KnowledgeExtractionPublic:
    return KnowledgeExtractionPublic.model_validate(
        {
            **record.__dict__,
            "source_title": record.source_title or record.source_url,
            "error_message": record.error_message,
        }
    )


def crawl_candidate_public(record: WebsiteCrawlCandidate) -> WebsiteCrawlCandidatePublic:
    return WebsiteCrawlCandidatePublic.model_validate(record)


def crawl_job_public(record: WebsiteCrawlJob) -> WebsiteCrawlJobPublic:
    return WebsiteCrawlJobPublic.model_validate(record)


def crawl_job_detail_public(record: WebsiteCrawlJob) -> WebsiteCrawlJobDetailPublic:
    candidates = sorted(record.candidates, key=lambda candidate: (-candidate.score, candidate.url))
    return WebsiteCrawlJobDetailPublic.model_validate(
        {
            **record.__dict__,
            "candidates": [crawl_candidate_public(candidate) for candidate in candidates],
        }
    )


def get_knowledge_document_for_company(
    db: Session,
    *,
    company_id: UUID,
    knowledge_document_id: UUID,
) -> KnowledgeDocument:
    record = db.get(KnowledgeDocument, knowledge_document_id)
    if record is None or record.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    return record


@router.get("/crawl-categories", response_model=list[CrawlCategoryPublic])
def list_crawl_categories() -> list[CrawlCategoryPublic]:
    return [CrawlCategoryPublic.model_validate(category) for category in category_options()]


@router.get("/crawls", response_model=list[WebsiteCrawlJobPublic])
def list_website_crawls(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WebsiteCrawlJobPublic]:
    company = current_company(db, current_user, company_id)
    return [crawl_job_public(record) for record in list_crawl_jobs(db, company_id=company.id)]


@router.post("/crawls", response_model=WebsiteCrawlJobDetailPublic, status_code=status.HTTP_201_CREATED)
def create_website_crawl(
    payload: WebsiteCrawlCreateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebsiteCrawlJobDetailPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    crawl_job = WebsiteCrawlJob(
        company_id=company.id,
        requested_by_user_id=current_user.id,
        root_url=str(payload.root_url),
        normalized_root_url=normalize_url(str(payload.root_url)),
        selected_categories=payload.selected_categories,
        custom_prompt=payload.custom_prompt.strip(),
        max_depth=payload.max_depth,
        max_pages=payload.max_pages,
    )
    db.add(crawl_job)
    db.flush()
    background_job = create_website_crawl_discovery_job(db, crawl_job=crawl_job)
    audit_event(
        db,
        event_type="website_crawl_requested",
        request=request,
        user_id=current_user.id,
        metadata={"crawl_job_id": str(crawl_job.id), "root_url": crawl_job.root_url},
    )
    db.commit()
    db.refresh(crawl_job)
    try:
        task = enqueue_background_job(background_job.id)
        background_job.celery_task_id = task.id or ""
        db.commit()
    except Exception as exc:
        crawl_job.status = "failed"
        crawl_job.error_message = f"Could not enqueue crawl discovery job: {exc}"[:1000]
        background_job.status = "failed"
        background_job.error_message = crawl_job.error_message
        db.commit()
    db.refresh(crawl_job)
    return crawl_job_detail_public(crawl_job)


@router.get("/crawls/{crawl_job_id}", response_model=WebsiteCrawlJobDetailPublic)
def get_website_crawl(
    crawl_job_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebsiteCrawlJobDetailPublic:
    company = current_company(db, current_user, company_id)
    crawl_job = db.scalar(
        select(WebsiteCrawlJob)
        .options(selectinload(WebsiteCrawlJob.candidates))
        .where(WebsiteCrawlJob.id == crawl_job_id, WebsiteCrawlJob.company_id == company.id)
    )
    if crawl_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website crawl job not found")
    return crawl_job_detail_public(crawl_job)


@router.patch("/crawls/{crawl_job_id}/schedule", response_model=WebsiteCrawlJobPublic)
def update_website_crawl_schedule(
    crawl_job_id: UUID,
    payload: WebsiteCrawlScheduleRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebsiteCrawlJobPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    crawl_job = crawl_job_for_company(db, company_id=company.id, crawl_job_id=crawl_job_id)
    crawl_job.recrawl_enabled = payload.recrawl_enabled
    crawl_job.recrawl_interval_days = payload.recrawl_interval_days if payload.recrawl_enabled else None
    crawl_job.next_recrawl_at = (
        utc_now() + timedelta(days=payload.recrawl_interval_days or 1)
        if payload.recrawl_enabled
        else None
    )
    audit_event(
        db,
        event_type="website_crawl_schedule_updated",
        request=request,
        user_id=current_user.id,
        metadata={"crawl_job_id": str(crawl_job.id), "enabled": crawl_job.recrawl_enabled},
    )
    db.commit()
    db.refresh(crawl_job)
    return crawl_job_public(crawl_job)


@router.post("/crawls/{crawl_job_id}/queue-pages", response_model=list[KnowledgeSourcePublic])
def queue_website_crawl_pages(
    crawl_job_id: UUID,
    payload: WebsiteCrawlQueueRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeSourcePublic]:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    crawl_job = db.scalar(
        select(WebsiteCrawlJob)
        .options(selectinload(WebsiteCrawlJob.candidates))
        .where(WebsiteCrawlJob.id == crawl_job_id, WebsiteCrawlJob.company_id == company.id)
    )
    if crawl_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Website crawl job not found")

    selected_ids = set(payload.selected_candidate_ids)
    selected_candidates = [candidate for candidate in crawl_job.candidates if candidate.id in selected_ids]
    manual_urls = [normalize_url(str(url)) for url in payload.manual_urls]
    if not selected_candidates and not manual_urls:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select or add at least one URL")

    queued_pairs = []
    for candidate in crawl_job.candidates:
        candidate.status = "selected" if candidate.id in selected_ids else "discarded"

    urls = [candidate.url for candidate in selected_candidates]
    urls.extend(url for url in manual_urls if url not in urls)
    for url in urls:
        knowledge_document, background_job = create_single_page_web_scrape_job(
            db,
            company=company,
            url=url,
            wait_seconds=payload.wait_seconds,
        )
        queued_pairs.append((knowledge_document, background_job))

    crawl_job.total_selected = len(urls)
    for candidate in selected_candidates:
        candidate.status = "queued"
    audit_event(
        db,
        event_type="website_crawl_pages_queued",
        request=request,
        user_id=current_user.id,
        metadata={"crawl_job_id": str(crawl_job.id), "url_count": len(urls)},
    )
    db.commit()
    for knowledge_document, background_job in queued_pairs:
        try:
            task = enqueue_background_job(background_job.id)
            background_job.celery_task_id = task.id or ""
        except Exception as exc:
            mark_job_failed(db, background_job, knowledge_document, f"Could not enqueue web scrape job: {exc}")
    db.commit()
    queued_documents = [knowledge_document for knowledge_document, _ in queued_pairs]
    for record in queued_documents:
        db.refresh(record)
    return [knowledge_source_public(record) for record in queued_documents]


@router.get("/web-pages", response_model=list[KnowledgeSourcePublic])
def list_web_pages(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeSourcePublic]:
    company = current_company(db, current_user, company_id)
    if enqueue_stale_queued_jobs(db, company_id=company.id, job_types=(SINGLE_PAGE_WEB_SCRAPE,)):
        db.commit()
    records = db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.company_id == company.id, KnowledgeDocument.source_type == "web_page")
        .order_by(KnowledgeDocument.created_at.desc())
    ).all()
    return [knowledge_source_public(record) for record in records]


@router.post("/web-pages", response_model=KnowledgeSourcePublic, status_code=status.HTTP_201_CREATED)
def create_web_page_scrape(
    payload: WebPageScrapeRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeSourcePublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    knowledge_document, background_job = create_single_page_web_scrape_job(
        db,
        company=company,
        url=str(payload.url),
        wait_seconds=payload.wait_seconds,
    )
    audit_event(
        db,
        event_type="web_page_scrape_requested",
        request=request,
        user_id=current_user.id,
        metadata={"knowledge_document_id": str(knowledge_document.id), "url": str(payload.url)},
    )
    db.commit()
    db.refresh(knowledge_document)

    try:
        task = enqueue_background_job(background_job.id)
        background_job.celery_task_id = task.id or ""
        db.commit()
        db.refresh(knowledge_document)
    except Exception as exc:
        mark_job_failed(db, background_job, knowledge_document, f"Could not enqueue web scrape job: {exc}")
        db.commit()
        db.refresh(knowledge_document)

    return knowledge_source_public(knowledge_document)


@router.get("/sources/{knowledge_document_id}/extraction", response_model=KnowledgeExtractionPublic)
def get_knowledge_extraction(
    knowledge_document_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeExtractionPublic:
    company = current_company(db, current_user, company_id)
    record = get_knowledge_document_for_company(
        db,
        company_id=company.id,
        knowledge_document_id=knowledge_document_id,
    )
    return knowledge_extraction_public(record)


@router.patch("/sources/{knowledge_document_id}/extraction", response_model=KnowledgeExtractionPublic)
def update_knowledge_extraction(
    knowledge_document_id: UUID,
    payload: KnowledgeExtractionUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> KnowledgeExtractionPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = get_knowledge_document_for_company(
        db,
        company_id=company.id,
        knowledge_document_id=knowledge_document_id,
    )

    record.extracted_text = payload.extracted_text
    record.char_count = len(payload.extracted_text)
    record.status = "completed"
    record.error_message = ""
    record.document_metadata = {
        **(record.document_metadata or {}),
        "manually_saved": True,
    }
    audit_event(
        db,
        event_type="knowledge_extraction_saved",
        request=request,
        user_id=current_user.id,
        metadata={"knowledge_document_id": str(record.id), "source_type": record.source_type},
    )
    db.commit()
    db.refresh(record)
    return knowledge_extraction_public(record)


@router.delete("/web-pages/{knowledge_document_id}", response_model=MessageResponse)
def delete_web_page(
    knowledge_document_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = get_knowledge_document_for_company(
        db,
        company_id=company.id,
        knowledge_document_id=knowledge_document_id,
    )
    if record.source_type != "web_page":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only web page sources can be removed here")

    db.delete(record)
    audit_event(
        db,
        event_type="web_page_knowledge_deleted",
        request=request,
        user_id=current_user.id,
        metadata={"knowledge_document_id": str(record.id), "url": record.source_url},
    )
    db.commit()
    return MessageResponse(message="Web page source removed")
