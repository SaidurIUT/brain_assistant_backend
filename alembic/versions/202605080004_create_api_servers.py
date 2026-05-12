"""create api servers

Revision ID: 202605080004
Revises: 202605080003
Create Date: 2026-05-08 00:04:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202605080004"
down_revision: str | None = "202605080003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_api_servers_company_id", "api_servers", ["company_id"])

    op.add_column(
        "api_documentation_sources",
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_servers.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_api_documentation_sources_server_id", "api_documentation_sources", ["server_id"])

    op.add_column(
        "api_endpoints",
        sa.Column(
            "server_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_servers.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_api_endpoints_server_id", "api_endpoints", ["server_id"])
    op.drop_constraint("uq_api_endpoints_company_method_path", "api_endpoints", type_="unique")
    op.create_unique_constraint(
        "uq_api_endpoints_server_method_path",
        "api_endpoints",
        ["server_id", "method", "path"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_api_endpoints_server_method_path", "api_endpoints", type_="unique")
    op.create_unique_constraint(
        "uq_api_endpoints_company_method_path",
        "api_endpoints",
        ["company_id", "method", "path"],
    )
    op.drop_index("ix_api_endpoints_server_id", table_name="api_endpoints")
    op.drop_column("api_endpoints", "server_id")
    op.drop_index("ix_api_documentation_sources_server_id", table_name="api_documentation_sources")
    op.drop_column("api_documentation_sources", "server_id")
    op.drop_index("ix_api_servers_company_id", table_name="api_servers")
    op.drop_table("api_servers")
