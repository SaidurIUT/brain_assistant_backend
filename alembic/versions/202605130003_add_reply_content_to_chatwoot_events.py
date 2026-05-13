"""add reply_content to chatwoot_events

Revision ID: 202605130003
Revises: 202605130002
Create Date: 2026-05-13 00:03:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202605130003"
down_revision: str | None = "202605130002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chatwoot_events", sa.Column("reply_content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chatwoot_events", "reply_content")
