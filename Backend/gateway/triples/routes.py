from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from accounts.runtime import AuthRuntime
from documents import service as documents_service
from .models import Triple
from .schemas import TripleEvidenceResponse, TripleResponse, TripleStatusUpdateRequest
from . import service

router = APIRouter(tags=["triples"])


def _runtime(request: Request) -> AuthRuntime:
    runtime: AuthRuntime | None = getattr(request.app.state, "accounts", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Triple servisi kullanılamıyor")
    return runtime


def _identity(request: Request) -> tuple[object | None, uuid.UUID]:
    return getattr(request.state, "user", None), request.state.visitor_id


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Geçersiz kimlik") from exc


def _triple_response(triple: Triple) -> TripleResponse:
    return TripleResponse(
        id=str(triple.id),
        document_id=str(triple.document_id),
        extraction_job_id=str(triple.extraction_job_id),
        workspace_id=str(triple.workspace_id),
        subject=triple.subject,
        subject_type=triple.subject_type,
        predicate=triple.predicate,
        object=triple.obj,
        object_type=triple.object_type,
        qualifiers=triple.qualifiers,
        status=triple.status,
        created_at=triple.created_at,
        updated_at=triple.updated_at,
        evidence=[
            TripleEvidenceResponse(
                id=str(evidence.id),
                source_text=evidence.source_text,
                char_start=evidence.char_start,
                char_end=evidence.char_end,
                created_at=evidence.created_at,
            )
            for evidence in triple.evidence
        ],
    )


@router.get("/api/extraction-jobs/{job_id}/triples", response_model=list[TripleResponse])
async def list_job_triples(job_id: str, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_id = _parse_uuid(job_id)

    async with runtime.sessions() as db:
        job = await documents_service.get_accessible_job(
            db, job_id=parsed_id, user=user, visitor_id=visitor_id
        )
        if job is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı")
        triples = await service.list_triples_for_job(db, job=job)

    return [_triple_response(triple) for triple in triples]


@router.get("/api/triples/{triple_id}", response_model=TripleResponse)
async def get_triple(triple_id: str, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_id = _parse_uuid(triple_id)

    async with runtime.sessions() as db:
        triple = await service.get_accessible_triple(
            db, triple_id=parsed_id, user=user, visitor_id=visitor_id
        )

    if triple is None:
        raise HTTPException(status_code=404, detail="Triple bulunamadı")
    return _triple_response(triple)


@router.patch("/api/triples/{triple_id}/status", response_model=TripleResponse)
async def update_triple_status(triple_id: str, body: TripleStatusUpdateRequest, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_id = _parse_uuid(triple_id)

    async with runtime.sessions() as db:
        triple = await service.get_accessible_triple(
            db, triple_id=parsed_id, user=user, visitor_id=visitor_id
        )
        if triple is None:
            raise HTTPException(status_code=404, detail="Triple bulunamadı")
        triple = await service.update_triple_status(db, triple=triple, status=body.status)

    return _triple_response(triple)
