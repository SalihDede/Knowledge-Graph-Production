from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from accounts.models import Base, utc_now


class TripleStatus(str, enum.Enum):
    candidate = "candidate"
    verified = "verified"
    rejected = "rejected"


class Triple(Base):
    __tablename__ = "triples"
    __table_args__ = (
        Index("ix_triples_document_id", "document_id"),
        Index("ix_triples_extraction_job_id", "extraction_job_id"),
        Index("ix_triples_workspace_id", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    extraction_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("extraction_jobs.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    obj: Mapped[str] = mapped_column("object", String(500), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    qualifiers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[TripleStatus] = mapped_column(
        Enum(TripleStatus, name="triple_status", native_enum=False, length=20),
        default=TripleStatus.candidate,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    evidence: Mapped[list["TripleEvidence"]] = relationship(
        back_populates="triple", cascade="all, delete-orphan", lazy="selectin"
    )


class TripleEvidence(Base):
    __tablename__ = "triple_evidence"
    __table_args__ = (
        Index("ix_triple_evidence_triple_id", "triple_id"),
        Index("ix_triple_evidence_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    triple_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("triples.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    triple: Mapped["Triple"] = relationship(back_populates="evidence")
