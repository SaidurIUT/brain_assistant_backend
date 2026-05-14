from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field


class WebPageScrapeRequest(BaseModel):
    url: AnyHttpUrl
    wait_seconds: int = Field(default=2, ge=0, le=10)


class KnowledgeSourcePublic(BaseModel):
    id: UUID
    source_type: str
    source_url: str
    source_title: str
    status: str
    char_count: int
    error_message: str
    created_at: datetime
    updated_at: datetime


class KnowledgeExtractionPublic(KnowledgeSourcePublic):
    extracted_text: str
    document_metadata: dict


class KnowledgeExtractionUpdateRequest(BaseModel):
    extracted_text: str = Field(max_length=5_000_000)
