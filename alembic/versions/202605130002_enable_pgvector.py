"""enable pgvector extension

Revision ID: 202605130002
Revises: 202605130001
Create Date: 2026-05-13 00:02:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202605130002"
down_revision: str | None = "202605130001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    pass  # never drop vector — may be used by other tables
