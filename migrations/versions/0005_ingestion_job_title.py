"""add ingestion job title

Revision ID: 0005_ingestion_job_title
Revises: 0004_api_keys
Create Date: 2026-06-15 00:00:04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005_ingestion_job_title"
down_revision = "0004_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("title", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "title")
