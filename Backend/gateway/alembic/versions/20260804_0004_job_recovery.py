"""Add recovery bookkeeping columns to extraction_jobs.

Revision ID: 20260804_0004
Revises: 20260803_0003
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260804_0004"
down_revision = "20260803_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extraction_jobs",
        sa.Column("recovery_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extraction_jobs",
        sa.Column("last_recovery_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extraction_jobs", "last_recovery_at")
    op.drop_column("extraction_jobs", "recovery_attempts")
