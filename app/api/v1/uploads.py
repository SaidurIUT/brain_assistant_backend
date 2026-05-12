from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.auth import User
from app.schemas.auth import MessageResponse
from app.schemas.uploads import UploadPublic
from app.services.auth import audit_event
from app.services.settings import current_company, require_company_admin
from app.services.uploads import delete_upload, get_upload_for_company, list_uploads, save_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])


def upload_public(record) -> UploadPublic:
    return UploadPublic.model_validate(
        {
            **record.__dict__,
            "download_url": f"/api/v1/uploads/documents/{record.id}/download",
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
    audit_event(
        db,
        event_type="document_uploaded",
        request=request,
        user_id=current_user.id,
        metadata={"upload_id": str(record.id), "filename": record.original_filename},
    )
    db.commit()
    db.refresh(record)
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
