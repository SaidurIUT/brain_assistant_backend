"""add email auth tokens

Revision ID: 202605080001
Revises: 202605070002
Create Date: 2026-05-08 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202605080001"
down_revision: str | None = "202605070002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")

    op.create_table(
        "auth_email_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "company_member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_members.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_email_tokens_user_id", "auth_email_tokens", ["user_id"])
    op.create_index("ix_auth_email_tokens_company_member_id", "auth_email_tokens", ["company_member_id"])
    op.create_index("ix_auth_email_tokens_email_normalized", "auth_email_tokens", ["email_normalized"])
    op.create_index("ix_auth_email_tokens_token_hash", "auth_email_tokens", ["token_hash"], unique=True)
    op.create_index("ix_auth_email_tokens_purpose", "auth_email_tokens", ["purpose"])


def downgrade() -> None:
    op.drop_table("auth_email_tokens")
    op.drop_column("users", "email_verified_at")
