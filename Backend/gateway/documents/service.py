from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import policy
from accounts.models import User
from .models import Document, ExtractionJob, JobStatus, Workspace
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
