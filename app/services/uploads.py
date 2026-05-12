from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.auth import Company, CompanyUpload, User

DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".md", ".txt", ".csv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
UPLOAD_CATEGORIES = {
    "documents": DOCUMENT_EXTENSIONS,
    "images": IMAGE_EXTENSIONS,
    "logos": IMAGE_EXTENSIONS,
}


def list_uploads(db: Session, company: Company, category: str = "documents") -> list[CompanyUpload]:
    ensure_category(category)
    return list(
        db.scalars(
            select(CompanyUpload)
            .where(CompanyUpload.company_id == company.id, CompanyUpload.category == category)
            .order_by(CompanyUpload.created_at.desc())
        )
    )


async def save_upload(
    db: Session,
    *,
    company: Company,
    user: User,
    upload: UploadFile,
    category: str = "documents",
) -> CompanyUpload:
    allowed_extensions = ensure_category(category)
    original_filename = Path(upload.filename or "upload").name
    extension = Path(original_filename).suffix.lower()
    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {allowed}",
        )

    target_dir = company_upload_dir(company, category)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid4().hex}{extension}"
    target_path = target_dir / stored_filename

    size_bytes = 0
    try:
        with target_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > settings.upload_max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File is larger than {settings.upload_max_bytes // (1024 * 1024)} MB",
                    )
                target.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    record = CompanyUpload(
        company_id=company.id,
        uploaded_by_user_id=user.id,
        category=category,
        original_filename=original_filename[:255],
        stored_filename=stored_filename,
        content_type=(upload.content_type or "application/octet-stream")[:120],
        size_bytes=size_bytes,
        storage_path=str(target_path),
    )
    db.add(record)
    db.flush()
    return record


def get_upload_for_company(db: Session, company: Company, upload_id) -> CompanyUpload:
    record = db.get(CompanyUpload, upload_id)
    if record is None or record.company_id != company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
    return record


def delete_upload(db: Session, record: CompanyUpload) -> None:
    Path(record.storage_path).unlink(missing_ok=True)
    db.delete(record)


def company_upload_dir(company: Company, category: str) -> Path:
    return Path(settings.upload_storage_path) / "companies" / str(company.id) / category


def ensure_category(category: str) -> set[str]:
    if category not in UPLOAD_CATEGORIES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload category not found")
    return UPLOAD_CATEGORIES[category]
