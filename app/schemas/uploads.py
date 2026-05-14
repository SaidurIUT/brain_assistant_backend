from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UploadPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    category: str
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    download_url: str
    extraction_status: str | None = None
    extracted_char_count: int | None = None
    extraction_error: str | None = None


class DocumentExtractionPublic(BaseModel):
    id: UUID
    upload_id: UUID
    status: str
    extracted_text: str
    char_count: int
    error_message: str
    document_metadata: dict
    updated_at: datetime


class DocumentExtractionUpdateRequest(BaseModel):
    extracted_text: str = Field(max_length=5_000_000)
