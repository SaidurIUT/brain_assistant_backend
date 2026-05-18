from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.common import TimestampMixin


class CompanySystemPrompt(Base, TimestampMixin):
    """The system prompt each tenant's bot uses when generating customer replies.

    One row per company (enforced by the unique constraint on company_id).
    Absence of a row means the tenant uses the built-in default. The runtime
    (rag_service.query_with_confidence) reads `content` and passes it as
    LightRAG's QueryParam.user_prompt.
    """

    __tablename__ = "company_system_prompts"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_company_system_prompts_company_id"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
