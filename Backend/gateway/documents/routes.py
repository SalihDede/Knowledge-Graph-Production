from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from accounts.runtime import AuthRuntime
from . import service
from .models import Document, ExtractionJob
from .schemas import (
    DocumentCreateRequest,
    DocumentDetail,
    DocumentSummary,
    ExtractionJobCreateRequest,
    ExtractionJobResponse,
)

router = APIRouter(tags=["documents"])


def _runtime(request: Request) -> AuthRuntime:
    runtime: AuthRuntime | None = getattr(request.app.state, "accounts", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Doküman servisi kullanılamıyor")
    return runtime


def _identity(request: Request) -> tuple[object | None, uuid.UUID]:
    return getattr(request.state, "user", None), request.state.visitor_id


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Geçersiz kimlik") from exc


def _document_summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=str(document.id),
        workspace_id=str(document.workspace_id),
        title=document.title,
        content_hash=document.content_hash,
        char_count=document.char_count,
        created_at=document.created_at,
    )


def _document_detail(document: Document) -> DocumentDetail:
    return DocumentDetail(
        **_document_summary(document).model_dump(),
        raw_text=document.raw_text,
        normalized_text=document.normalized_text,
    )


def _job_response(job: ExtractionJob) -> ExtractionJobResponse:
    return ExtractionJobResponse(
        id=str(job.id),
        document_id=str(job.document_id),
        workspace_id=str(job.workspace_id),
        status=job.status,
        pipeline_fingerprint=job.pipeline_fingerprint,
        result=job.result,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/api/documents", response_model=DocumentDetail)
async def create_document(body: DocumentCreateRequest, request: Request, response: Response):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)

    async with runtime.sessions() as db:
        workspace = await service.get_or_create_workspace(db, user=user, visitor_id=visitor_id)
        document, created = await service.create_document(
            db,
            workspace=workspace,
            user=user,
            visitor_id=visitor_id,
            text=body.text,
            title=body.title,
        )

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _document_detail(document)


@router.get("/api/documents", response_model=list[DocumentSummary])
async def list_documents(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)

    async with runtime.sessions() as db:
        workspace = await service.get_or_create_workspace(db, user=user, visitor_id=visitor_id)
        documents = await service.list_documents(db, workspace=workspace, limit=limit, offset=offset)

    return [_document_summary(document) for document in documents]


@router.get("/api/documents/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_id = _parse_uuid(document_id)

    async with runtime.sessions() as db:
        document = await service.get_accessible_document(
            db, document_id=parsed_id, user=user, visitor_id=visitor_id
        )

    if document is None:
        raise HTTPException(status_code=404, detail="Doküman bulunamadı")
    return _document_detail(document)


@router.post("/api/extraction-jobs", response_model=ExtractionJobResponse)
async def create_extraction_job(
    body: ExtractionJobCreateRequest, request: Request, response: Response
):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    document_id = _parse_uuid(body.document_id)

    async with runtime.sessions() as db:
        document = await service.get_accessible_document(
            db, document_id=document_id, user=user, visitor_id=visitor_id
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Doküman bulunamadı")

        job, created = await service.create_or_reuse_extraction_job(
            db,
            document=document,
            user=user,
            visitor_id=visitor_id,
            kg_type=body.kg_type,
            prompt_type=body.prompt_type,
            embedding_model=body.embedding_model,
            ontology_language=body.ontology_language,
            model=body.model,
        )

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _job_response(job)


@router.get("/api/extraction-jobs/{job_id}", response_model=ExtractionJobResponse)
async def get_extraction_job(job_id: str, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_id = _parse_uuid(job_id)

    async with runtime.sessions() as db:
        job = await service.get_accessible_job(
            db, job_id=parsed_id, user=user, visitor_id=visitor_id
        )

    if job is None:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı")
    return _job_response(job)
