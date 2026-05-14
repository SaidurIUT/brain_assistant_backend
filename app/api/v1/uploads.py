from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import MessageResponse
from app.schemas.uploads import DocumentExtractionPublic, DocumentExtractionUpdateRequest, UploadPublic
from app.services.auth import audit_event
from app.services.jobs import create_document_extraction_job, enqueue_background_job, mark_job_failed
from app.services.settings import current_company, require_company_admin
from app.services.uploads import delete_upload, get_upload_for_company, list_uploads, save_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


def upload_public(record) -> UploadPublic:
    knowledge_document = getattr(record, "knowledge_document", None)
    return UploadPublic.model_validate(
        {
            **record.__dict__,
            "download_url": f"/api/v1/uploads/documents/{record.id}/download",
            "extraction_status": knowledge_document.status if knowledge_document else None,
            "extracted_char_count": knowledge_document.char_count if knowledge_document else None,
            "extraction_error": knowledge_document.error_message if knowledge_document else None,
        }
    )


def extraction_public(record) -> DocumentExtractionPublic:
    knowledge_document = getattr(record, "knowledge_document", None)
    if knowledge_document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction not found")
    return DocumentExtractionPublic.model_validate(
        {
            **knowledge_document.__dict__,
            "error_message": knowledge_document.error_message,
        }
    )


@router.get("/documents", response_model=list[UploadPublic])
def list_documents(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UploadPublic]:
    company = current_company(db, current_user, company_id)
    return [upload_public(record) for record in list_uploads(db, company, "documents")]


@router.post("/documents", response_model=UploadPublic, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = await save_upload(db, company=company, user=current_user, upload=file, category="documents")
    knowledge_document, background_job = create_document_extraction_job(db, upload=record)
    audit_event(
        db,
        event_type="document_uploaded",
        request=request,
        user_id=current_user.id,
        metadata={"upload_id": str(record.id), "filename": record.original_filename},
    )
    db.commit()
    db.refresh(record)
    db.refresh(knowledge_document)
    try:
        task = enqueue_background_job(background_job.id)
        background_job.celery_task_id = task.id or ""
        db.commit()
        db.refresh(record)
        db.refresh(knowledge_document)
    except Exception as exc:
        mark_job_failed(db, background_job, knowledge_document, f"Could not enqueue extraction job: {exc}")
        db.commit()
        db.refresh(record)
        db.refresh(knowledge_document)
    return upload_public(record)


@router.get("/documents/{upload_id}/download")
def download_document(
    upload_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    company = current_company(db, current_user, company_id)
    record = get_upload_for_company(db, company, upload_id)
    return FileResponse(
        record.storage_path,
        media_type=record.content_type,
        filename=record.original_filename,
    )


@router.get("/documents/{upload_id}/extraction", response_model=DocumentExtractionPublic)
def get_document_extraction(
    upload_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentExtractionPublic:
    company = current_company(db, current_user, company_id)
    record = get_upload_for_company(db, company, upload_id)
    return extraction_public(record)


@router.patch("/documents/{upload_id}/extraction", response_model=DocumentExtractionPublic)
def update_document_extraction(
    upload_id: UUID,
    payload: DocumentExtractionUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentExtractionPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = get_upload_for_company(db, company, upload_id)
    knowledge_document = getattr(record, "knowledge_document", None)
    if knowledge_document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extraction not found")

    knowledge_document.extracted_text = payload.extracted_text
    knowledge_document.char_count = len(payload.extracted_text)
    knowledge_document.status = "completed"
    knowledge_document.error_message = ""
    knowledge_document.document_metadata = {
        **(knowledge_document.document_metadata or {}),
        "manually_saved": True,
    }
    audit_event(
        db,
        event_type="document_extraction_saved",
        request=request,
        user_id=current_user.id,
        metadata={"upload_id": str(record.id), "filename": record.original_filename},
    )
    db.commit()
    db.refresh(record)
    return extraction_public(record)


@router.delete("/documents/{upload_id}", response_model=MessageResponse)
def remove_document(
    upload_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = get_upload_for_company(db, company, upload_id)
    delete_upload(db, record)
    audit_event(db, event_type="document_deleted", request=request, user_id=current_user.id)
    db.commit()
    return MessageResponse(message="Document removed")
