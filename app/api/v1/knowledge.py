from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.auth import KnowledgeDocument, User
from app.schemas.auth import MessageResponse
from app.schemas.knowledge import (
    KnowledgeExtractionPublic,
    KnowledgeExtractionUpdateRequest,
    KnowledgeSourcePublic,
    WebPageScrapeRequest,
)
from app.services.auth import audit_event
from app.services.jobs import create_single_page_web_scrape_job, enqueue_background_job, mark_job_failed
from app.services.settings import current_company, require_company_admin

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


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


@router.get("/web-pages", response_model=list[KnowledgeSourcePublic])
def list_web_pages(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[KnowledgeSourcePublic]:
    company = current_company(db, current_user, company_id)
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
