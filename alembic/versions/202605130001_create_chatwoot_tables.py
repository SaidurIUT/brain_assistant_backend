"""create chatwoot tables

Revision ID: 202605130001
Revises: 202605120001
Create Date: 2026-05-13 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202605130001"
down_revision: str | None = "202605120001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chatwoot_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chatwoot_base_url", sa.String(500), nullable=False),
        sa.Column("chatwoot_account_id", sa.BigInteger(), nullable=False),
        sa.Column("chatwoot_inbox_id", sa.BigInteger(), nullable=False),
        sa.Column("chatwoot_agent_bot_id", sa.BigInteger(), nullable=False),
        sa.Column("chatwoot_agent_bot_token", sa.Text(), nullable=True),
        sa.Column("webhook_secret", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "chatwoot_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("delivery_id", sa.String(255), nullable=False),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=True),
        sa.Column("inbox_id", sa.BigInteger(), nullable=True),
        sa.Column("conversation_display_id", sa.Integer(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("message_type", sa.String(50), nullable=True),
        sa.Column("sender_type", sa.String(50), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(50), nullable=False, server_default="received"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("delivery_id", name="uq_chatwoot_events_delivery_id"),
    )


def downgrade() -> None:
    op.drop_table("chatwoot_events")
    op.drop_table("chatwoot_connections")
