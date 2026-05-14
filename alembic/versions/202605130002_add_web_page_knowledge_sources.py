"""add web page knowledge sources

Revision ID: 202605130002
Revises: 202605130001
Create Date: 2026-05-13 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202605130002"
down_revision: str | None = "202605130001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("source_type", sa.String(length=40), server_default="upload", nullable=False),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_url", sa.String(length=2000), server_default="", nullable=False),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("source_title", sa.String(length=500), server_default="", nullable=False),
    )
    op.alter_column("knowledge_documents", "upload_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_index("ix_knowledge_documents_source_type", "knowledge_documents", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_documents_source_type", table_name="knowledge_documents")
    op.alter_column("knowledge_documents", "upload_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("knowledge_documents", "source_title")
    op.drop_column("knowledge_documents", "source_url")
    op.drop_column("knowledge_documents", "source_type")
