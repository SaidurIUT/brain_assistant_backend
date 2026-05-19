from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.common import TimestampMixin


class ExternalSourceConnection(Base, TimestampMixin):
    __tablename__ = "external_source_connections"
    __table_args__ = (
        UniqueConstraint("company_id", "provider", "account_email", name="uq_external_connections_account"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connected_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    account_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    account_name: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="connected", index=True, nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    token_type: Mapped[str] = mapped_column(String(40), default="Bearer", nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_interval_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="external_source_connections")
    folders: Mapped[list["ExternalSourceFolder"]] = relationship(
        "ExternalSourceFolder", back_populates="connection", cascade="all, delete-orphan"
    )
    items: Mapped[list["ExternalSourceItem"]] = relationship(
        "ExternalSourceItem", back_populates="connection", cascade="all, delete-orphan"
    )
    sync_runs: Mapped[list["ExternalSourceSyncRun"]] = relationship(
        "ExternalSourceSyncRun", back_populates="connection", cascade="all, delete-orphan"
    )


class ExternalSourceFolder(Base, TimestampMixin):
    __tablename__ = "external_source_folders"
    __table_args__ = (
        UniqueConstraint("connection_id", "drive_id", "provider_folder_id", name="uq_external_folders_provider"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_source_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider_folder_id: Mapped[str] = mapped_column(String(500), nullable=False)
    drive_id: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    connection: Mapped["ExternalSourceConnection"] = relationship("ExternalSourceConnection", back_populates="folders")


class ExternalSourceItem(Base, TimestampMixin):
    __tablename__ = "external_source_items"
    __table_args__ = (
        UniqueConstraint("connection_id", "drive_id", "provider_file_id", name="uq_external_items_provider"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_source_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folder_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_source_folders.id", ondelete="SET NULL"), index=True, nullable=True
    )
    knowledge_document_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_documents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    provider_file_id: Mapped[str] = mapped_column(String(500), nullable=False)
    drive_id: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    web_url: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    checksum: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    etag: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="discovered", index=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    document_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    connection: Mapped["ExternalSourceConnection"] = relationship("ExternalSourceConnection", back_populates="items")
    folder: Mapped["ExternalSourceFolder | None"] = relationship("ExternalSourceFolder")
    knowledge_document: Mapped["KnowledgeDocument | None"] = relationship("KnowledgeDocument")


class ExternalSourceSyncRun(Base, TimestampMixin):
    __tablename__ = "external_source_sync_runs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("external_source_connections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    current_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    trigger: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True, nullable=False)
    total_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_queued: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection: Mapped["ExternalSourceConnection"] = relationship("ExternalSourceConnection", back_populates="sync_runs")
    current_job: Mapped["BackgroundJob | None"] = relationship("BackgroundJob")


class ExternalSourceOAuthState(Base, TimestampMixin):
    __tablename__ = "external_source_oauth_states"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    redirect_path: Mapped[str] = mapped_column(String(500), default="/dashboard/data-sources", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
