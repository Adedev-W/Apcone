"""add pdf ingest job metadata

Revision ID: 0002_pdf_ingest_jobs
Revises: 0001_initial_rag_storage
Create Date: 2026-06-09 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_pdf_ingest_jobs"
down_revision = "0001_initial_rag_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("file_name", sa.String(length=255), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("mime_type", sa.String(length=127), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("storage_path", sa.String(length=512), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("parser_name", sa.String(length=64), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column(
        "ingestion_jobs",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "progress")
    op.drop_column("ingestion_jobs", "page_count")
    op.drop_column("ingestion_jobs", "parser_name")
    op.drop_column("ingestion_jobs", "storage_path")
    op.drop_column("ingestion_jobs", "mime_type")
    op.drop_column("ingestion_jobs", "file_name")
