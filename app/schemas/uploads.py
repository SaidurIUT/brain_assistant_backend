from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
