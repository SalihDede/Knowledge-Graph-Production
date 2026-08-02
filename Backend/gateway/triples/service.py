from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from accounts.models import User
from documents.models import Document, ExtractionJob, Workspace
from documents.service import workspace_belongs_to_identity
from .models import Triple, TripleEvidence, TripleStatus


@dataclass
class TripleEvidenceInput:
    source_text: str
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class TripleInput:
    subject: str
    predicate: str
    object: str
    subject_type: str | None = None
    object_type: str | None = None
    qualifiers: list | None = None
    evidence: list[TripleEvidenceInput] = field(default_factory=list)


async def record_triples_for_job(
    db: AsyncSession,
    *,
    job: ExtractionJob,
    document: Document,
    triples: list[TripleInput],
) -> list[Triple]:
    created: list[Triple] = []
    for item in triples:
        triple = Triple(
            document_id=document.id,
            extraction_job_id=job.id,
            workspace_id=job.workspace_id,
            subject=item.subject,
            subject_type=item.subject_type,
            predicate=item.predicate,
            obj=item.object,
            object_type=item.object_type,
            qualifiers=item.qualifiers,
            status=TripleStatus.candidate,
        )
        triple.evidence = [
            TripleEvidence(
                document_id=document.id,
                source_text=evidence.source_text,
                char_start=evidence.char_start,
                char_end=evidence.char_end,
            )
            for evidence in item.evidence
        ]
        db.add(triple)
        created.append(triple)

    await db.commit()
    for triple in created:
        await db.refresh(triple)
    return created


async def list_triples_for_job(db: AsyncSession, *, job: ExtractionJob) -> list[Triple]:
    result = await db.scalars(
        select(Triple)
        .where(Triple.extraction_job_id == job.id)
        .order_by(Triple.created_at.asc())
    )
    return list(result)


async def get_accessible_triple(
    db: AsyncSession,
    *,
    triple_id: uuid.UUID,
    user: User | None,
    visitor_id: uuid.UUID,
) -> Triple | None:
    triple = await db.get(Triple, triple_id)
    if triple is None:
        return None
    workspace = await db.get(Workspace, triple.workspace_id)
    if workspace is None or not workspace_belongs_to_identity(
        workspace, user=user, visitor_id=visitor_id
    ):
        return None
    return triple


async def update_triple_status(
    db: AsyncSession, *, triple: Triple, status: TripleStatus
) -> Triple:
    triple.status = status
    await db.commit()
    await db.refresh(triple)
    return triple
