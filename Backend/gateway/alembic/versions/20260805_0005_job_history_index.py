"""Replace extraction_jobs.workspace_id index with a (workspace_id, created_at)
composite index for the workspace history listing.

Revision ID: 20260805_0005
Revises: 20260804_0004
Create Date: 2026-08-05
"""

from alembic import op


revision = "20260805_0005"
down_revision = "20260804_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_extraction_jobs_workspace_id", table_name="extraction_jobs")
    op.create_index(
        "ix_extraction_jobs_workspace_created",
        "extraction_jobs",
        ["workspace_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_jobs_workspace_created", table_name="extraction_jobs")
    op.create_index(
        "ix_extraction_jobs_workspace_id",
        "extraction_jobs",
        ["workspace_id"],
    )
