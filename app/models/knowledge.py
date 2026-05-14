from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.datetime import utc_now
from app.db.session import Base
from app.models.common import TimestampMixin


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    upload_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company_uploads.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    current_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), default="upload", index=True, nullable=False)
    source_url: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    document_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped["Company"] = relationship("Company", back_populates="knowledge_documents")
    upload: Mapped["CompanyUpload | None"] = relationship("CompanyUpload", back_populates="knowledge_document")
    current_job: Mapped["BackgroundJob | None"] = relationship("BackgroundJob", back_populates="knowledge_documents")


class WebsiteCrawlJob(Base, TimestampMixin):
    __tablename__ = "website_crawl_jobs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    current_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    root_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    normalized_root_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True, nullable=False)
    selected_categories: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    custom_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    total_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_matched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_selected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recrawl_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recrawl_interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_recrawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recrawl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped["Company"] = relationship("Company")
    requested_by: Mapped["User | None"] = relationship("User", foreign_keys=[requested_by_user_id])
    current_job: Mapped["BackgroundJob | None"] = relationship("BackgroundJob")
    candidates: Mapped[list["WebsiteCrawlCandidate"]] = relationship(
        "WebsiteCrawlCandidate",
        back_populates="crawl_job",
        cascade="all, delete-orphan",
    )


class WebsiteCrawlCandidate(Base, TimestampMixin):
    __tablename__ = "website_crawl_candidates"
    __table_args__ = (
        UniqueConstraint("crawl_job_id", "url", name="uq_website_crawl_candidates_job_url"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    crawl_job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("website_crawl_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(40), default="bfs", nullable=False)
    matched_categories: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    match_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="candidate", index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    crawl_job: Mapped["WebsiteCrawlJob"] = relationship("WebsiteCrawlJob", back_populates="candidates")
