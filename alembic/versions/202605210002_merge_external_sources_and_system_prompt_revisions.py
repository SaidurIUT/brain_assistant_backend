"""merge external sources and system prompt revisions

Revision ID: 202605210002
Revises: 202605190001, 202605210001
Create Date: 2026-05-21 00:02:00.000000
"""

from collections.abc import Sequence

revision: str = "202605210002"
down_revision: tuple[str, str] = ("202605190001", "202605210001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
