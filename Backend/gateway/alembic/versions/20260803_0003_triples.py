"""Add pipeline params to extraction_jobs and create triples/triple_evidence.

Revision ID: 20260803_0003
Revises: 20260802_0002
Create Date: 2026-08-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260803_0003"
down_revision = "20260802_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extraction_jobs", sa.Column("model", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("extraction_jobs", sa.Column("kg_type", sa.String(length=50), nullable=False, server_default="wikipedia"))
    op.add_column("extraction_jobs", sa.Column("prompt_type", sa.String(length=50), nullable=False, server_default="temel"))
    op.add_column("extraction_jobs", sa.Column("embedding_model", sa.String(length=100), nullable=False, server_default="contriever"))
    op.add_column("extraction_jobs", sa.Column("ontology_language", sa.String(length=10), nullable=False, server_default="en"))
    op.add_column("extraction_jobs", sa.Column("pipeline_version", sa.String(length=20), nullable=False, server_default="v1"))

    op.create_index(
        "ux_extraction_jobs_active_document_fingerprint",
        "extraction_jobs",
        ["document_id", "pipeline_fingerprint"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "triples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_job_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("subject_type", sa.String(length=120), nullable=True),
        sa.Column("predicate", sa.String(length=255), nullable=False),
        sa.Column("object", sa.String(length=500), nullable=False),
        sa.Column("object_type", sa.String(length=120), nullable=True),
        sa.Column("qualifiers", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("candidate", "verified", "rejected", name="triple_status", native_enum=False, length=20),
            nullable=False,
            server_default="candidate",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_triples_document_id", "triples", ["document_id"])
    op.create_index("ix_triples_extraction_job_id", "triples", ["extraction_job_id"])
    op.create_index("ix_triples_workspace_id", "triples", ["workspace_id"])

    op.create_table(
        "triple_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("triple_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["triple_id"], ["triples.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_triple_evidence_triple_id", "triple_evidence", ["triple_id"])
    op.create_index("ix_triple_evidence_document_id", "triple_evidence", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_triple_evidence_document_id", table_name="triple_evidence")
    op.drop_index("ix_triple_evidence_triple_id", table_name="triple_evidence")
    op.drop_table("triple_evidence")

    op.drop_index("ix_triples_workspace_id", table_name="triples")
    op.drop_index("ix_triples_extraction_job_id", table_name="triples")
    op.drop_index("ix_triples_document_id", table_name="triples")
    op.drop_table("triples")

    op.drop_index("ux_extraction_jobs_active_document_fingerprint", table_name="extraction_jobs")

    op.drop_column("extraction_jobs", "pipeline_version")
    op.drop_column("extraction_jobs", "ontology_language")
    op.drop_column("extraction_jobs", "embedding_model")
    op.drop_column("extraction_jobs", "prompt_type")
    op.drop_column("extraction_jobs", "kg_type")
    op.drop_column("extraction_jobs", "model")
