from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import policy
from accounts.models import User
from .models import (
    Document,
    DocumentSegment,
    DocumentSourceType,
    ExtractionJob,
    IngestionStatus,
    JobStatus,
    SegmentType,
    Workspace,
)
from .normalization import (
    PIPELINE_VERSION,
    compute_content_hash,
    compute_pipeline_fingerprint,
    normalize_text,
)

REUSABLE_JOB_STATUSES = (JobStatus.queued, JobStatus.running, JobStatus.completed)
ACTIVE_JOB_STATUSES = (JobStatus.queued, JobStatus.running)


async def get_or_create_workspace(
    db: AsyncSession,
    *,
    user: User | None,
    visitor_id: uuid.UUID,
) -> Workspace:
    if user is not None:
        workspace = await db.scalar(
            select(Workspace).where(Workspace.owner_user_id == user.id)
        )
        if workspace is not None:
            return workspace

        claimed_workspace = await db.scalar(
            select(Workspace).where(Workspace.owner_visitor_id == visitor_id)
        )
        if claimed_workspace is not None:
            claimed_workspace.owner_user_id = user.id
            claimed_workspace.owner_visitor_id = None
            await db.commit()
            await db.refresh(claimed_workspace)
            return claimed_workspace

        workspace = Workspace(owner_user_id=user.id)
    else:
        workspace = await db.scalar(
            select(Workspace).where(Workspace.owner_visitor_id == visitor_id)
        )
        if workspace is not None:
            return workspace
        workspace = Workspace(owner_visitor_id=visitor_id)

    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


def workspace_belongs_to_identity(
    workspace: Workspace, *, user: User | None, visitor_id: uuid.UUID
) -> bool:
    if user is not None:
        return workspace.owner_user_id == user.id or workspace.owner_visitor_id == visitor_id
    return workspace.owner_visitor_id == visitor_id


async def create_document(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User | None,
    visitor_id: uuid.UUID,
    text: str,
    title: str | None,
) -> tuple[Document, bool]:
    normalized_text = normalize_text(text)
    content_hash = compute_content_hash(normalized_text)

    existing = await db.scalar(
        select(Document).where(
            Document.workspace_id == workspace.id,
            Document.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, False

    document = Document(
        workspace_id=workspace.id,
        created_by_user_id=user.id if user is not None else None,
        created_by_visitor_id=visitor_id if user is None else None,
        title=title,
        raw_text=text,
        normalized_text=normalized_text,
        content_hash=content_hash,
        char_count=len(normalized_text),
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document, True


async def get_accessible_document(
    db: AsyncSession,
    *,
    document_id: uuid.UUID,
    user: User | None,
    visitor_id: uuid.UUID,
) -> Document | None:
    document = await db.get(Document, document_id)
    if document is None:
        return None
    workspace = await db.get(Workspace, document.workspace_id)
    if workspace is None or not workspace_belongs_to_identity(
        workspace, user=user, visitor_id=visitor_id
    ):
        return None
    return document


async def list_documents(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
) -> list[Document]:
    result = await db.scalars(
        select(Document)
        .where(Document.workspace_id == workspace.id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


async def _find_reusable_job(
    db: AsyncSession, *, document_id: uuid.UUID, fingerprint: str
) -> ExtractionJob | None:
    return await db.scalar(
        select(ExtractionJob)
        .where(
            ExtractionJob.document_id == document_id,
            ExtractionJob.pipeline_fingerprint == fingerprint,
            ExtractionJob.status.in_(REUSABLE_JOB_STATUSES),
        )
        .order_by(ExtractionJob.created_at.desc())
    )


async def count_active_jobs(db: AsyncSession, *, workspace_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(ExtractionJob)
        .where(
            ExtractionJob.workspace_id == workspace_id,
            ExtractionJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    return count or 0


async def create_or_reuse_extraction_job(
    db: AsyncSession,
    *,
    document: Document,
    user: User | None,
    visitor_id: uuid.UUID,
    kg_type: str,
    prompt_type: str,
    embedding_model: str,
    ontology_language: str,
    model: str,
) -> tuple[ExtractionJob, bool]:
    if document.ingestion_status != IngestionStatus.ready:
        raise policy.DocumentNotReadyError(document.ingestion_status.value)

    document_id = document.id
    workspace_id = document.workspace_id
    fingerprint = compute_pipeline_fingerprint(
        kg_type=kg_type,
        prompt_type=prompt_type,
        embedding_model=embedding_model,
        ontology_language=ontology_language,
        model=model,
    )

    existing = await _find_reusable_job(db, document_id=document_id, fingerprint=fingerprint)
    if existing is not None:
        return existing, False

    active_count = await count_active_jobs(db, workspace_id=workspace_id)
    if active_count >= policy.MAX_ACTIVE_JOBS_PER_WORKSPACE:
        raise policy.ActiveJobLimitExceeded(policy.MAX_ACTIVE_JOBS_PER_WORKSPACE)

    job = ExtractionJob(
        document_id=document_id,
        workspace_id=workspace_id,
        created_by_user_id=user.id if user is not None else None,
        created_by_visitor_id=visitor_id if user is None else None,
        model=model,
        kg_type=kg_type,
        prompt_type=prompt_type,
        embedding_model=embedding_model,
        ontology_language=ontology_language,
        pipeline_version=PIPELINE_VERSION,
        pipeline_fingerprint=fingerprint,
        status=JobStatus.queued,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _find_reusable_job(db, document_id=document_id, fingerprint=fingerprint)
        if existing is not None:
            return existing, False
        raise
    await db.refresh(job)
    return job, True


async def get_accessible_job(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    user: User | None,
    visitor_id: uuid.UUID,
) -> ExtractionJob | None:
    job = await db.get(ExtractionJob, job_id)
    if job is None:
        return None
    workspace = await db.get(Workspace, job.workspace_id)
    if workspace is None or not workspace_belongs_to_identity(
        workspace, user=user, visitor_id=visitor_id
    ):
        return None
    return job


DOCUMENT_PREVIEW_LENGTH = 200


@dataclass
class JobHistoryEntry:
    job: ExtractionJob
    document_title: str | None
    document_preview: str
    document_source_type: DocumentSourceType
    document_page_count: int | None
    document_source_url: str | None


def _build_preview(text: str | None, length: int = DOCUMENT_PREVIEW_LENGTH) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= length:
        return normalized
    return normalized[:length].rstrip() + "…"


async def list_jobs_for_workspace(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    limit: int,
    offset: int,
    status: JobStatus | None = None,
    document_id: uuid.UUID | None = None,
) -> list[JobHistoryEntry]:
    """Job history for a workspace, newest first. Joins in just the document
    title and a short preview -- never the full raw/normalized text -- so the
    listing stays cheap regardless of document size."""
    stmt = (
        select(
            ExtractionJob,
            Document.title,
            Document.normalized_text,
            Document.source_type,
            Document.page_count,
            Document.source_url,
        )
        .join(Document, Document.id == ExtractionJob.document_id)
        .where(ExtractionJob.workspace_id == workspace_id)
    )
    if status is not None:
        stmt = stmt.where(ExtractionJob.status == status)
    if document_id is not None:
        stmt = stmt.where(ExtractionJob.document_id == document_id)

    stmt = stmt.order_by(ExtractionJob.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    return [
        JobHistoryEntry(
            job=job,
            document_title=title,
            document_preview=_build_preview(text),
            document_source_type=source_type,
            document_page_count=page_count,
            document_source_url=source_url,
        )
        for job, title, text, source_type, page_count, source_url in result.all()
    ]


# ── PDF / URL ingestion ──────────────────────────────────────────────────────


@dataclass
class SegmentInput:
    segment_type: SegmentType
    ordinal: int
    text: str
    char_start: int
    char_end: int
    page_number: int | None = None
    metadata: dict | None = None


async def create_pdf_document(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User | None,
    visitor_id: uuid.UUID,
    storage_key: str,
    title: str | None,
) -> Document:
    document = Document(
        workspace_id=workspace.id,
        created_by_user_id=user.id if user is not None else None,
        created_by_visitor_id=visitor_id if user is None else None,
        title=title,
        source_type=DocumentSourceType.pdf,
        ingestion_status=IngestionStatus.pending,
        storage_key=storage_key,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def get_document_by_source_url(
    db: AsyncSession, *, workspace_id: uuid.UUID, source_url: str
) -> Document | None:
    return await db.scalar(
        select(Document)
        .where(Document.workspace_id == workspace_id, Document.source_url == source_url)
        .order_by(Document.created_at.desc())
    )


async def create_url_document(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User | None,
    visitor_id: uuid.UUID,
    url: str,
    title: str | None,
) -> tuple[Document, bool]:
    """Reuses a pending/processing/ready document already ingesting this
    exact URL in the workspace instead of scraping it again; a document that
    previously failed may be retried as a fresh row."""
    existing = await get_document_by_source_url(db, workspace_id=workspace.id, source_url=url)
    if existing is not None and existing.ingestion_status != IngestionStatus.failed:
        return existing, False

    document = Document(
        workspace_id=workspace.id,
        created_by_user_id=user.id if user is not None else None,
        created_by_visitor_id=visitor_id if user is None else None,
        title=title,
        source_type=DocumentSourceType.url,
        ingestion_status=IngestionStatus.pending,
        source_url=url,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document, True


async def mark_ingestion_processing(db: AsyncSession, *, document: Document) -> None:
    document.ingestion_status = IngestionStatus.processing
    document.ingestion_error = None
    await db.commit()


async def mark_ingestion_ready(
    db: AsyncSession,
    *,
    document: Document,
    raw_text: str,
    normalized_text: str,
    page_count: int | None = None,
    file_hash: str | None = None,
) -> None:
    document.raw_text = raw_text
    document.normalized_text = normalized_text
    document.content_hash = compute_content_hash(normalized_text)
    document.char_count = len(normalized_text)
    document.page_count = page_count
    document.file_hash = file_hash
    document.ingestion_status = IngestionStatus.ready
    document.ingestion_error = None
    try:
        await db.commit()
    except IntegrityError:
        # Another document in this workspace already holds this exact
        # (normalized) content -- extremely rare for pdf/url sources, but
        # the unique (workspace_id, content_hash) index would otherwise
        # surface as an unhandled 500.
        await db.rollback()
        raise policy.PolicyError(
            "Bu içerik aynı çalışma alanında zaten başka bir doküman olarak kayıtlı",
            status_code=409,
        )


async def mark_ingestion_failed(db: AsyncSession, *, document: Document, error_message: str) -> None:
    document.ingestion_status = IngestionStatus.failed
    document.ingestion_error = error_message[:2000]
    await db.commit()


async def replace_segments_for_document(
    db: AsyncSession, *, document: Document, segments: list[SegmentInput]
) -> int:
    """Atomically replaces every segment recorded for a document -- mirrors
    triples.service.replace_triples_for_job so ingestion retries never
    accumulate duplicate segments."""
    await db.execute(delete(DocumentSegment).where(DocumentSegment.document_id == document.id))
    for segment in segments:
        db.add(DocumentSegment(
            document_id=document.id,
            segment_type=segment.segment_type,
            page_number=segment.page_number,
            ordinal=segment.ordinal,
            text=segment.text,
            char_start=segment.char_start,
            char_end=segment.char_end,
            segment_metadata=segment.metadata,
        ))
    await db.commit()
    return len(segments)


async def count_segments(db: AsyncSession, *, document_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(DocumentSegment)
        .where(DocumentSegment.document_id == document_id)
    )
    return count or 0
