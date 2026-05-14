"""create website crawl tables

Revision ID: 202605150001
Revises: 202605140004
Create Date: 2026-05-15 00:01:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202605150001"
down_revision: str | None = "202605140004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "website_crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("current_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("root_url", sa.String(length=2000), nullable=False),
        sa.Column("normalized_root_url", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("selected_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("custom_prompt", sa.Text(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False),
        sa.Column("total_discovered", sa.Integer(), nullable=False),
        sa.Column("total_matched", sa.Integer(), nullable=False),
        sa.Column("total_selected", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("recrawl_enabled", sa.Boolean(), nullable=False),
        sa.Column("recrawl_interval_days", sa.Integer(), nullable=True),
        sa.Column("next_recrawl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_recrawl_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_job_id"], ["background_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_website_crawl_jobs_company_id", "website_crawl_jobs", ["company_id"])
    op.create_index("ix_website_crawl_jobs_current_job_id", "website_crawl_jobs", ["current_job_id"])
    op.create_index("ix_website_crawl_jobs_status", "website_crawl_jobs", ["status"])

    op.create_table(
        "website_crawl_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("discovery_source", sa.String(length=40), nullable=False),
        sa.Column("matched_categories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["website_crawl_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_job_id", "url", name="uq_website_crawl_candidates_job_url"),
    )
    op.create_index("ix_website_crawl_candidates_company_id", "website_crawl_candidates", ["company_id"])
    op.create_index("ix_website_crawl_candidates_crawl_job_id", "website_crawl_candidates", ["crawl_job_id"])
    op.create_index("ix_website_crawl_candidates_status", "website_crawl_candidates", ["status"])


def downgrade() -> None:
    op.drop_index("ix_website_crawl_candidates_status", table_name="website_crawl_candidates")
    op.drop_index("ix_website_crawl_candidates_crawl_job_id", table_name="website_crawl_candidates")
    op.drop_index("ix_website_crawl_candidates_company_id", table_name="website_crawl_candidates")
    op.drop_table("website_crawl_candidates")

    op.drop_index("ix_website_crawl_jobs_status", table_name="website_crawl_jobs")
    op.drop_index("ix_website_crawl_jobs_current_job_id", table_name="website_crawl_jobs")
    op.drop_index("ix_website_crawl_jobs_company_id", table_name="website_crawl_jobs")
    op.drop_table("website_crawl_jobs")
