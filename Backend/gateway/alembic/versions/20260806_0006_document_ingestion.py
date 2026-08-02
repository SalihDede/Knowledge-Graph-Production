"""Add PDF/URL ingestion fields to documents and a document_segments table.

Revision ID: 20260806_0006
Revises: 20260805_0005
Create Date: 2026-08-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260806_0006"
down_revision = "20260805_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("documents", "raw_text", existing_type=sa.Text(), nullable=True)
    op.alter_column("documents", "normalized_text", existing_type=sa.Text(), nullable=True)
    op.alter_column("documents", "content_hash", existing_type=sa.String(length=64), nullable=True)
    op.alter_column("documents", "char_count", existing_type=sa.Integer(), nullable=True)

    op.add_column(
        "documents",
        sa.Column(
            "source_type",
            sa.Enum("text", "pdf", "url", name="document_source_type", native_enum=False, length=20),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "ingestion_status",
            sa.Enum(
                "pending", "processing", "ready", "failed",
                name="document_ingestion_status", native_enum=False, length=20,
            ),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column("documents", sa.Column("ingestion_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("storage_key", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("file_hash", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))

    op.create_table(
        "document_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "segment_type",
            sa.Enum("page", "paragraph", name="document_segment_type", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_segments_document_id", "document_segments", ["document_id"])
    op.create_index(
        "ux_document_segments_document_ordinal",
        "document_segments",
        ["document_id", "segment_type", "ordinal"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_document_segments_document_ordinal", table_name="document_segments")
    op.drop_index("ix_document_segments_document_id", table_name="document_segments")
    op.drop_table("document_segments")

    op.drop_column("documents", "page_count")
    op.drop_column("documents", "file_hash")
    op.drop_column("documents", "storage_key")
    op.drop_column("documents", "source_url")
    op.drop_column("documents", "ingestion_error")
    op.drop_column("documents", "ingestion_status")
    op.drop_column("documents", "source_type")

    op.alter_column("documents", "char_count", existing_type=sa.Integer(), nullable=False)
    op.alter_column("documents", "content_hash", existing_type=sa.String(length=64), nullable=False)
    op.alter_column("documents", "normalized_text", existing_type=sa.Text(), nullable=False)
    op.alter_column("documents", "raw_text", existing_type=sa.Text(), nullable=False)
