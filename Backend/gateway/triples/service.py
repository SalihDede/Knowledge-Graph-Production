from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, select
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


async def replace_triples_for_job(
    db: AsyncSession,
    *,
    job: ExtractionJob,
    document: Document,
    triples: list[TripleInput],
) -> list[Triple]:
    """Atomically replaces every triple recorded for a job.

    Extraction jobs can retry after a partial/failed write (broker redelivery,
    worker crash mid-task). Wiping the job's previous triples before
    re-inserting keeps re-runs idempotent instead of accumulating duplicates.
    """
    await db.execute(
        delete(TripleEvidence).where(
            TripleEvidence.triple_id.in_(
                select(Triple.id).where(Triple.extraction_job_id == job.id)
            )
        )
    )
    await db.execute(delete(Triple).where(Triple.extraction_job_id == job.id))
    return await record_triples_for_job(db, job=job, document=document, triples=triples)


def build_triple_inputs_from_raw(raw_triplets: list[dict], normalized_text: str) -> list[TripleInput]:
    """Maps the Turkish-keyed extraction output (baş/ilişki/uç/...) to TripleInput
    rows, locating each triple's source sentence inside the document text."""
    inputs: list[TripleInput] = []
    for raw in raw_triplets:
        subject = (raw.get("baş") or "").strip()
        predicate = (raw.get("ilişki") or "").strip()
        obj = (raw.get("uç") or "").strip()
        if not subject or not predicate or not obj:
            continue

        evidence: list[TripleEvidenceInput] = []
        source_text = (raw.get("kaynak_cumle") or "").strip()
        if source_text:
            char_start = normalized_text.find(source_text)
            evidence.append(
                TripleEvidenceInput(
                    source_text=source_text,
                    char_start=char_start if char_start != -1 else None,
                    char_end=char_start + len(source_text) if char_start != -1 else None,
                )
            )

        inputs.append(
            TripleInput(
                subject=subject,
                subject_type=raw.get("baş_tipi") or None,
                predicate=predicate,
                object=obj,
                object_type=raw.get("uç_tipi") or None,
                qualifiers=raw.get("qualifiers") or None,
                evidence=evidence,
            )
        )
    return inputs


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
