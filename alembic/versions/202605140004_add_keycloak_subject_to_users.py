"""add keycloak subject to users

Revision ID: 202605140004
Revises: 202605140003
Create Date: 2026-05-14 00:04:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202605140004"
down_revision: str | None = "202605140003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("keycloak_subject", sa.String(length=255), nullable=True))
    op.create_index("ix_users_keycloak_subject", "users", ["keycloak_subject"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_keycloak_subject", table_name="users")
    op.drop_column("users", "keycloak_subject")
