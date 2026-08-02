"""Create workspaces, documents and extraction_jobs.

Revision ID: 20260802_0002
Revises: 20260802_0001
Create Date: 2026-08-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_0002"
down_revision = "20260802_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False, server_default="Default"),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_visitor_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_visitor_id"], ["anonymous_visitors.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(owner_user_id IS NOT NULL) != (owner_visitor_id IS NOT NULL)",
            name="ck_workspaces_single_owner",
        ),
    )
    op.create_index(
        "ux_workspaces_owner_user_id",
        "workspaces",
        ["owner_user_id"],
        unique=True,
        postgresql_where=sa.text("owner_user_id IS NOT NULL"),
    )
    op.create_index(
        "ux_workspaces_owner_visitor_id",
        "workspaces",
        ["owner_visitor_id"],
        unique=True,
        postgresql_where=sa.text("owner_visitor_id IS NOT NULL"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_visitor_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_visitor_id"], ["anonymous_visitors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index(
        "ux_documents_workspace_content_hash",
        "documents",
        ["workspace_id", "content_hash"],
        unique=True,
    )

    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_visitor_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", name="extraction_job_status", native_enum=False, length=20),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_visitor_id"], ["anonymous_visitors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_extraction_jobs_document_id", "extraction_jobs", ["document_id"])
    op.create_index("ix_extraction_jobs_workspace_id", "extraction_jobs", ["workspace_id"])
    op.create_index(
        "ix_extraction_jobs_document_fingerprint",
        "extraction_jobs",
        ["document_id", "pipeline_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_jobs_document_fingerprint", table_name="extraction_jobs")
    op.drop_index("ix_extraction_jobs_workspace_id", table_name="extraction_jobs")
    op.drop_index("ix_extraction_jobs_document_id", table_name="extraction_jobs")
    op.drop_table("extraction_jobs")

    op.drop_index("ux_documents_workspace_content_hash", table_name="documents")
    op.drop_index("ix_documents_workspace_id", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ux_workspaces_owner_visitor_id", table_name="workspaces")
    op.drop_index("ux_workspaces_owner_user_id", table_name="workspaces")
    op.drop_table("workspaces")
