"""add company api base url

Revision ID: 202605080003
Revises: 202605080002
Create Date: 2026-05-08 00:03:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202605080003"
down_revision: str | None = "202605080002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("api_base_url", sa.String(length=1000), server_default="", nullable=False),
    )
    op.alter_column("companies", "api_base_url", server_default=None)


def downgrade() -> None:
    op.drop_column("companies", "api_base_url")
