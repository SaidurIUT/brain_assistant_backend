"""create external source tables

Revision ID: 202605190001
Revises: 202605180001
Create Date: 2026-05-19 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202605190001"
down_revision: str | None = "202605180001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_source_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connected_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("account_email", sa.String(length=320), nullable=False),
        sa.Column("account_name", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("token_type", sa.String(length=40), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_interval_hours", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "provider", "account_email", name="uq_external_connections_account"),
    )
    op.create_index("ix_external_source_connections_company_id", "external_source_connections", ["company_id"])
    op.create_index("ix_external_source_connections_provider", "external_source_connections", ["provider"])
    op.create_index("ix_external_source_connections_status", "external_source_connections", ["status"])

    op.create_table(
        "external_source_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_source_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_folder_id", sa.String(length=500), nullable=False),
        sa.Column("drive_id", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("recursive", sa.Boolean(), nullable=False),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "drive_id", "provider_folder_id", name="uq_external_folders_provider"),
    )
    op.create_index("ix_external_source_folders_company_id", "external_source_folders", ["company_id"])
    op.create_index("ix_external_source_folders_connection_id", "external_source_folders", ["connection_id"])

    op.create_table(
        "external_source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_source_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folder_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_source_folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("knowledge_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider_file_id", sa.String(length=500), nullable=False),
        sa.Column("drive_id", sa.String(length=500), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=300), nullable=False),
        sa.Column("web_url", sa.String(length=2000), nullable=False),
        sa.Column("checksum", sa.String(length=255), nullable=False),
        sa.Column("etag", sa.String(length=500), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("document_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connection_id", "drive_id", "provider_file_id", name="uq_external_items_provider"),
    )
    op.create_index("ix_external_source_items_company_id", "external_source_items", ["company_id"])
    op.create_index("ix_external_source_items_connection_id", "external_source_items", ["connection_id"])
    op.create_index("ix_external_source_items_folder_id", "external_source_items", ["folder_id"])
    op.create_index("ix_external_source_items_knowledge_document_id", "external_source_items", ["knowledge_document_id"])
    op.create_index("ix_external_source_items_status", "external_source_items", ["status"])

    op.create_table(
        "external_source_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("external_source_connections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("total_seen", sa.Integer(), nullable=False),
        sa.Column("total_queued", sa.Integer(), nullable=False),
        sa.Column("total_synced", sa.Integer(), nullable=False),
        sa.Column("total_skipped", sa.Integer(), nullable=False),
        sa.Column("total_deleted", sa.Integer(), nullable=False),
        sa.Column("total_failed", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_external_source_sync_runs_company_id", "external_source_sync_runs", ["company_id"])
    op.create_index("ix_external_source_sync_runs_connection_id", "external_source_sync_runs", ["connection_id"])
    op.create_index("ix_external_source_sync_runs_current_job_id", "external_source_sync_runs", ["current_job_id"])
    op.create_index("ix_external_source_sync_runs_status", "external_source_sync_runs", ["status"])

    op.create_table(
        "external_source_oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("redirect_path", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("state_hash", name="uq_external_oauth_states_state_hash"),
    )
    op.create_index("ix_external_source_oauth_states_company_id", "external_source_oauth_states", ["company_id"])
    op.create_index("ix_external_source_oauth_states_state_hash", "external_source_oauth_states", ["state_hash"])
    op.create_index("ix_external_source_oauth_states_user_id", "external_source_oauth_states", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_external_source_oauth_states_user_id", table_name="external_source_oauth_states")
    op.drop_index("ix_external_source_oauth_states_state_hash", table_name="external_source_oauth_states")
    op.drop_index("ix_external_source_oauth_states_company_id", table_name="external_source_oauth_states")
    op.drop_table("external_source_oauth_states")

    op.drop_index("ix_external_source_sync_runs_status", table_name="external_source_sync_runs")
    op.drop_index("ix_external_source_sync_runs_current_job_id", table_name="external_source_sync_runs")
    op.drop_index("ix_external_source_sync_runs_connection_id", table_name="external_source_sync_runs")
    op.drop_index("ix_external_source_sync_runs_company_id", table_name="external_source_sync_runs")
    op.drop_table("external_source_sync_runs")

    op.drop_index("ix_external_source_items_status", table_name="external_source_items")
    op.drop_index("ix_external_source_items_knowledge_document_id", table_name="external_source_items")
    op.drop_index("ix_external_source_items_folder_id", table_name="external_source_items")
    op.drop_index("ix_external_source_items_connection_id", table_name="external_source_items")
    op.drop_index("ix_external_source_items_company_id", table_name="external_source_items")
    op.drop_table("external_source_items")

    op.drop_index("ix_external_source_folders_connection_id", table_name="external_source_folders")
    op.drop_index("ix_external_source_folders_company_id", table_name="external_source_folders")
    op.drop_table("external_source_folders")

    op.drop_index("ix_external_source_connections_status", table_name="external_source_connections")
    op.drop_index("ix_external_source_connections_provider", table_name="external_source_connections")
    op.drop_index("ix_external_source_connections_company_id", table_name="external_source_connections")
    op.drop_table("external_source_connections")
