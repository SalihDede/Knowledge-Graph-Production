from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from accounts.models import Base, utc_now
from .normalization import PIPELINE_VERSION


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class DocumentSourceType(str, enum.Enum):
    text = "text"
    pdf = "pdf"
    url = "url"


class IngestionStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class SegmentType(str, enum.Enum):
    page = "page"
    paragraph = "paragraph"


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "(owner_user_id IS NOT NULL) != (owner_visitor_id IS NOT NULL)",
            name="ck_workspaces_single_owner",
        ),
        Index(
            "ux_workspaces_owner_user_id",
            "owner_user_id",
            unique=True,
            postgresql_where=text("owner_user_id IS NOT NULL"),
            sqlite_where=text("owner_user_id IS NOT NULL"),
        ),
        Index(
            "ux_workspaces_owner_visitor_id",
            "owner_visitor_id",
            unique=True,
            postgresql_where=text("owner_visitor_id IS NOT NULL"),
            sqlite_where=text("owner_visitor_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), default="Default")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    owner_visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("anonymous_visitors.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_workspace_id", "workspace_id"),
        # NULL content_hash rows (pdf/url docs still ingesting) never collide:
        # both PostgreSQL and SQLite treat NULLs as distinct in unique indexes.
        Index("ux_documents_workspace_content_hash", "workspace_id", "content_hash", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("anonymous_visitors.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[DocumentSourceType] = mapped_column(
        Enum(DocumentSourceType, name="document_source_type", native_enum=False, length=20),
        default=DocumentSourceType.text,
        nullable=False,
    )
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="document_ingestion_status", native_enum=False, length=20),
        default=IngestionStatus.ready,
        nullable=False,
    )
    ingestion_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Populated once ingestion completes (always for text; after extraction
    # for pdf/url), so these stay nullable while a document is still pending.
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"
    __table_args__ = (
        Index("ix_extraction_jobs_document_id", "document_id"),
        # Covers plain workspace_id lookups too (leftmost-prefix), so it
        # replaces a separate single-column index; the history listing
        # filters by workspace_id and always orders by created_at desc.
        Index("ix_extraction_jobs_workspace_created", "workspace_id", "created_at"),
        Index("ix_extraction_jobs_document_fingerprint", "document_id", "pipeline_fingerprint"),
        Index(
            "ux_extraction_jobs_active_document_fingerprint",
            "document_id",
            "pipeline_fingerprint",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("anonymous_visitors.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    kg_type: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_type: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    ontology_language: Mapped[str] = mapped_column(String(10), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(20), default=PIPELINE_VERSION, nullable=False)
    pipeline_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="extraction_job_status", native_enum=False, length=20),
        default=JobStatus.queued,
        nullable=False,
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_recovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class DocumentSegment(Base):
    __tablename__ = "document_segments"
    __table_args__ = (
        Index("ix_document_segments_document_id", "document_id"),
        Index(
            "ux_document_segments_document_ordinal",
            "document_id",
            "segment_type",
            "ordinal",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    segment_type: Mapped[SegmentType] = mapped_column(
        Enum(SegmentType, name="document_segment_type", native_enum=False, length=20),
        nullable=False,
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    # Mapped attribute avoids shadowing SQLAlchemy's reserved `Base.metadata`;
    # the actual column is still named "metadata".
    segment_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
