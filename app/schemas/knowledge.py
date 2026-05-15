from datetime import datetime
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class WebPageScrapeRequest(BaseModel):
    url: AnyHttpUrl
    wait_seconds: int = Field(default=2, ge=0, le=10)


class KnowledgeSourcePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class CrawlCategoryPublic(BaseModel):
    id: str
    label: str
    description: str


class WebsiteCrawlCreateRequest(BaseModel):
    root_url: AnyHttpUrl
    selected_categories: list[str] = Field(default_factory=list)
    custom_prompt: str = Field(default="", max_length=2000)
    max_depth: int = Field(default=5, ge=1, le=5)
    max_pages: int = Field(default=300, ge=25, le=1000)


class WebsiteCrawlScheduleRequest(BaseModel):
    recrawl_enabled: bool = False
    recrawl_interval_days: int | None = Field(default=None, ge=1, le=90)


class WebsiteCrawlCandidatePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    title: str
    depth: int
    discovery_source: str
    matched_categories: list[str]
    match_reason: str
    status: str
    score: int
    created_at: datetime
    updated_at: datetime


class WebsiteCrawlJobPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    root_url: str
    normalized_root_url: str
    status: str
    selected_categories: list[str]
    custom_prompt: str
    max_depth: int
    max_pages: int
    total_discovered: int
    total_matched: int
    total_selected: int
    error_message: str
    recrawl_enabled: bool
    recrawl_interval_days: int | None
    next_recrawl_at: datetime | None
    last_recrawl_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WebsiteCrawlJobDetailPublic(WebsiteCrawlJobPublic):
    candidates: list[WebsiteCrawlCandidatePublic]


class WebsiteCrawlQueueRequest(BaseModel):
    selected_candidate_ids: list[UUID] = Field(default_factory=list)
    manual_urls: list[AnyHttpUrl] = Field(default_factory=list)
    wait_seconds: int = Field(default=2, ge=0, le=10)
