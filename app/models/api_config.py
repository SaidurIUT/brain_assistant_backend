from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.common import TimestampMixin


class ApiServer(Base, TimestampMixin):
    __tablename__ = "api_servers"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="api_servers")
    documentation_sources: Mapped[list["ApiDocumentationSource"]] = relationship(
        "ApiDocumentationSource",
        back_populates="server", cascade="all, delete-orphan"
    )
    endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        "ApiEndpoint", back_populates="server", cascade="all, delete-orphan"
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

    company: Mapped["Company"] = relationship("Company", back_populates="api_documentation_sources")
    server: Mapped["ApiServer | None"] = relationship("ApiServer", back_populates="documentation_sources")
    endpoints: Mapped[list["ApiEndpoint"]] = relationship(
        "ApiEndpoint", back_populates="source", cascade="all, delete-orphan"
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

    company: Mapped["Company"] = relationship("Company", back_populates="api_endpoints")
    server: Mapped["ApiServer | None"] = relationship("ApiServer", back_populates="endpoints")
    source: Mapped["ApiDocumentationSource | None"] = relationship(
        "ApiDocumentationSource", back_populates="endpoints"
    )
