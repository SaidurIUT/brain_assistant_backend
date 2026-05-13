from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.datetime import utc_now
from app.db.session import Base


class ChatwootConnection(Base):
    """
    One row per Chatwoot account + inbox that Brain Assistant is connected to.

    Created via the Chatwoot settings UI (US3). Read by the webhook ingestion
    service to verify signatures, and by the Celery worker to post AI replies.

    Encryption of token/secret fields is deferred to a later story.
    Currently stored as plaintext.
    """

    __tablename__ = "chatwoot_connections"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )

    chatwoot_base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    chatwoot_account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chatwoot_inbox_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chatwoot_agent_bot_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Stored as plaintext for now; encryption added in a later story
    chatwoot_agent_bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ChatwootEvent(Base):
    """
    Audit log of every AgentBot webhook event received from Chatwoot.

    One row per delivery. delivery_id is unique — if Chatwoot retries the same
    delivery, the second INSERT fails and we return 200 without reprocessing.

    conversation_display_id is the #N shown in the Chatwoot UI, not the DB id.
    The Chatwoot messages API uses display_id in the URL path.
    """

    __tablename__ = "chatwoot_events"
    __table_args__ = (UniqueConstraint("delivery_id", name="uq_chatwoot_events_delivery_id"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)

    delivery_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)

    account_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    inbox_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conversation_display_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sender_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # received → stored, pending AI processing
    # processed → AI replied (or skipped — outgoing messages)
    # failed → error; row stays for retry/debugging
    status: Mapped[str] = mapped_column(String(50), default="received", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_incoming_message(self) -> bool:
        return self.event_name == "message_created" and self.message_type == "incoming"
