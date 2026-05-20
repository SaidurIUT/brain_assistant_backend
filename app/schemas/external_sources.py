from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ExternalSourceProvider = Literal["google_drive", "onedrive"]


class ExternalSourceOAuthStartRequest(BaseModel):
    redirect_path: str = Field(default="/dashboard/data-sources", max_length=500)


class ExternalSourceOAuthStartResponse(BaseModel):
    auth_url: str


class ExternalSourceFolderSelection(BaseModel):
    provider_folder_id: str = Field(max_length=500)
    drive_id: str = Field(default="", max_length=500)
    name: str = Field(max_length=500)
    path: str = Field(default="", max_length=2000)
    recursive: bool = True
    sync_enabled: bool = True


class ExternalSourceFolderSelectionRequest(BaseModel):
    folders: list[ExternalSourceFolderSelection] = Field(default_factory=list, max_length=50)


class ProviderFolderPublic(BaseModel):
    provider_folder_id: str
    drive_id: str = ""
    name: str
    path: str
    parent_id: str = ""


class ExternalSourceFolderPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_folder_id: str
    drive_id: str
    name: str
    path: str
    recursive: bool
    sync_enabled: bool
    created_at: datetime
    updated_at: datetime


class ExternalSourceSyncRunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connection_id: UUID
    trigger: str
    status: str
    total_seen: int
    total_queued: int
    total_synced: int
    total_skipped: int
    total_deleted: int
    total_failed: int
    error_message: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExternalSourceConnectionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    provider: str
    account_email: str
    account_name: str
    status: str
    scopes: list[str]
    last_sync_at: datetime | None
    next_sync_at: datetime | None
    sync_interval_hours: int
    error_message: str
    selected_folder_count: int = 0
    latest_sync_run: ExternalSourceSyncRunPublic | None = None
    created_at: datetime
    updated_at: datetime


class ExternalSourceItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    connection_id: UUID
    knowledge_document_id: UUID | None = None
    provider_file_id: str
    drive_id: str
    name: str
    mime_type: str
    web_url: str
    checksum: str
    etag: str
    modified_at: datetime | None
    size_bytes: int
    status: str
    last_synced_at: datetime | None
    last_seen_at: datetime | None
    error_message: str
    extraction_status: str | None = None
    extracted_char_count: int | None = None
    extraction_error: str | None = None
    created_at: datetime
    updated_at: datetime
