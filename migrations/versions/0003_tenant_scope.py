"""add tenant scope isolation

Revision ID: 0003_tenant_scope
Revises: 0002_pdf_ingest_jobs
Create Date: 2026-06-12 00:00:02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_tenant_scope"
down_revision = "0002_pdf_ingest_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("tenant_id", sa.String(length=80), nullable=False, server_default="default"),
    )
    op.add_column(
        "documents",
        sa.Column("scope", sa.String(length=80), nullable=False, server_default="default"),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("tenant_id", sa.String(length=80), nullable=False, server_default="default"),
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("scope", sa.String(length=80), nullable=False, server_default="default"),
    )

    op.drop_index(op.f("ix_documents_checksum"), table_name="documents")
    op.drop_constraint("documents_checksum_key", "documents", type_="unique")
    op.create_index("ix_documents_tenant_scope", "documents", ["tenant_id", "scope"])
    op.create_unique_constraint(
        "uq_documents_tenant_scope_checksum",
        "documents",
        ["tenant_id", "scope", "checksum"],
    )
    op.create_index("ix_ingestion_jobs_tenant_scope", "ingestion_jobs", ["tenant_id", "scope"])

    op.alter_column("documents", "tenant_id", server_default=None)
    op.alter_column("documents", "scope", server_default=None)
    op.alter_column("ingestion_jobs", "tenant_id", server_default=None)
    op.alter_column("ingestion_jobs", "scope", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_tenant_scope", table_name="ingestion_jobs")
    op.drop_constraint("uq_documents_tenant_scope_checksum", "documents", type_="unique")
    op.drop_index("ix_documents_tenant_scope", table_name="documents")
    op.create_unique_constraint("documents_checksum_key", "documents", ["checksum"])
    op.create_index(op.f("ix_documents_checksum"), "documents", ["checksum"], unique=True)

    op.drop_column("ingestion_jobs", "scope")
    op.drop_column("ingestion_jobs", "tenant_id")
    op.drop_column("documents", "scope")
    op.drop_column("documents", "tenant_id")
