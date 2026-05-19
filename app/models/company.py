from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.common import TimestampMixin


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
        "BrandSettings",
        back_populates="company", cascade="all, delete-orphan", uselist=False
    )
    members: Mapped[list["CompanyMember"]] = relationship(
        "CompanyMember", back_populates="company", cascade="all, delete-orphan"
    )
    api_documentation_sources: Mapped[list["ApiDocumentationSource"]] = relationship(
        "ApiDocumentationSource",
        back_populates="company", cascade="all, delete-orphan"
    )
    api_endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        "ApiEndpoint", back_populates="company", cascade="all, delete-orphan"
    )
    api_servers: Mapped[list["ApiServer"]] = relationship(
        "ApiServer", back_populates="company", cascade="all, delete-orphan"
    )
    uploads: Mapped[list["CompanyUpload"]] = relationship(
        "CompanyUpload", back_populates="company", cascade="all, delete-orphan"
    )
    background_jobs: Mapped[list["BackgroundJob"]] = relationship(
        "BackgroundJob",
        back_populates="company", cascade="all, delete-orphan"
    )
    knowledge_documents: Mapped[list["KnowledgeDocument"]] = relationship(
        "KnowledgeDocument",
        back_populates="company", cascade="all, delete-orphan"
    )
    external_source_connections: Mapped[list["ExternalSourceConnection"]] = relationship(
        "ExternalSourceConnection",
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

    company: Mapped["Company"] = relationship("Company", back_populates="brand_settings")


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

    company: Mapped["Company"] = relationship("Company", back_populates="members")
    user: Mapped["User | None"] = relationship("User", back_populates="memberships", foreign_keys=[user_id])
