from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.datetime import utc_now
from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="AuthSession.user_id"
    )
    memberships: Mapped[list["CompanyMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="CompanyMember.user_id"
    )

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), default="Untitled company", nullable=False)
    industry: Mapped[str] = mapped_column(String(120), default="Other", nullable=False)
    team_size: Mapped[str] = mapped_column(String(80), default="1-5 agents", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    primary_language: Mapped[str] = mapped_column(String(80), default="English", nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    brand_settings: Mapped["BrandSettings"] = relationship(
        back_populates="company", cascade="all, delete-orphan", uselist=False
    )
    members: Mapped[list["CompanyMember"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    api_documentation_sources: Mapped[list["ApiDocumentationSource"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    api_endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    api_servers: Mapped[list["ApiServer"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    uploads: Mapped[list["CompanyUpload"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class BrandSettings(Base, TimestampMixin):
    __tablename__ = "brand_settings"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    workspace_name: Mapped[str] = mapped_column(String(160), default="Brain Assistant Workspace", nullable=False)
    assistant_name: Mapped[str] = mapped_column(String(160), default="Brain Assistant", nullable=False)
    widget_greeting: Mapped[str] = mapped_column(
        String(260), default="Hi! I am Brain Assistant. How can I help?", nullable=False
    )
    primary_color: Mapped[str] = mapped_column(String(20), default="#6366f1", nullable=False)
    accent_color: Mapped[str] = mapped_column(String(20), default="#06b6d4", nullable=False)
    widget_background: Mapped[str] = mapped_column(String(20), default="#ffffff", nullable=False)
    logo_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    company: Mapped[Company] = relationship(back_populates="brand_settings")


class CompanyMember(Base, TimestampMixin):
    __tablename__ = "company_members"
    __table_args__ = (UniqueConstraint("company_id", "email_normalized", name="uq_company_members_email"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(40), default="agent", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="invited", nullable=False)
    invited_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    company: Mapped[Company] = relationship(back_populates="members")
    user: Mapped[User | None] = relationship(
        back_populates="memberships", foreign_keys=[user_id]
    )


class ApiServer(Base, TimestampMixin):
    __tablename__ = "api_servers"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)

    company: Mapped[Company] = relationship(back_populates="api_servers")
    documentation_sources: Mapped[list["ApiDocumentationSource"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )
    endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )


class ApiDocumentationSource(Base, TimestampMixin):
    __tablename__ = "api_documentation_sources"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    server_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_servers.id", ondelete="CASCADE"), index=True, nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(40), default="openapi", nullable=False)
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    version: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    raw_document: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    company: Mapped[Company] = relationship(back_populates="api_documentation_sources")
    server: Mapped[ApiServer | None] = relationship(back_populates="documentation_sources")
    endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class ApiEndpoint(Base, TimestampMixin):
    __tablename__ = "api_endpoints"
    __table_args__ = (
        UniqueConstraint("server_id", "method", "path", name="uq_api_endpoints_server_method_path"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    server_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_servers.id", ondelete="CASCADE"), index=True, nullable=True
    )
    source_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_documentation_sources.id", ondelete="SET NULL"), index=True, nullable=True
    )
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    summary: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    operation_id: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    auth_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_type: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    parameters: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    request_body: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    responses: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_accessible_to_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    company: Mapped[Company] = relationship(back_populates="api_endpoints")
    server: Mapped[ApiServer | None] = relationship(back_populates="endpoints")
    source: Mapped[ApiDocumentationSource | None] = relationship(back_populates="endpoints")


class CompanyUpload(Base, TimestampMixin):
    __tablename__ = "company_uploads"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(40), default="documents", index=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream", nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(700), nullable=False)

    company: Mapped[Company] = relationship(back_populates="uploads")
    uploaded_by: Mapped[User | None] = relationship(foreign_keys=[uploaded_by_user_id])


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    refresh_token_family: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), index=True, nullable=False)
    rotated_from_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions", foreign_keys=[user_id])
    rotated_from: Mapped["AuthSession | None"] = relationship(remote_side=[id])

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utc_now()


class AuthEmailToken(Base):
    __tablename__ = "auth_email_tokens"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    company_member_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("company_members.id", ondelete="CASCADE"), index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuthAuditEvent(Base):
    __tablename__ = "auth_audit_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
