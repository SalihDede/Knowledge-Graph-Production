from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

import policy
import storage
from accounts.runtime import AuthRuntime
from ingestion.errors import IngestionError
from ingestion.ssrf import assert_public_url
from triples import service as triples_service
# Imported as modules (not `from worker.tasks import run_extraction_job`):
# worker.celery_app / worker.tasks(.ingestion_tasks) can be the very first
# module imported in the process (e.g. `celery -A worker.celery_app worker`),
# which in turn imports documents.models -> documents (this package). Pulling
# a specific name out of them here would try to read it off a still-partial
# module in that case; a bare module reference resolved at call time doesn't.
from worker import ingestion_tasks as worker_ingestion_tasks
from worker import tasks as worker_tasks
from . import service
from .models import Document, ExtractionJob, JobStatus
from .schemas import (
    DocumentCreateRequest,
    DocumentDetail,
    DocumentIngestionResponse,
    DocumentPdfCreateRequest,
    DocumentSummary,
    DocumentUrlCreateRequest,
    ExtractionJobCreateRequest,
    ExtractionJobResponse,
    ExtractionJobSummary,
    PresignUploadRequest,
    PresignUploadResponse,
)

logger = logging.getLogger(__name__)
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
        source_type=document.source_type,
        ingestion_status=document.ingestion_status,
        content_hash=document.content_hash,
        char_count=document.char_count,
        page_count=document.page_count,
        created_at=document.created_at,
    )


def _document_detail(document: Document) -> DocumentDetail:
    return DocumentDetail(
        **_document_summary(document).model_dump(),
        raw_text=document.raw_text,
        normalized_text=document.normalized_text,
        source_url=document.source_url,
        ingestion_error=document.ingestion_error,
    )


def _job_response(job: ExtractionJob) -> ExtractionJobResponse:
    return ExtractionJobResponse(
        id=str(job.id),
        document_id=str(job.document_id),
        workspace_id=str(job.workspace_id),
        model=job.model,
        kg_type=job.kg_type,
        prompt_type=job.prompt_type,
        embedding_model=job.embedding_model,
        ontology_language=job.ontology_language,
        pipeline_version=job.pipeline_version,
        status=job.status,
        pipeline_fingerprint=job.pipeline_fingerprint,
        result=job.result,
        error_message=job.error_message,
        recovery_attempts=job.recovery_attempts,
        last_recovery_at=job.last_recovery_at,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/api/documents", response_model=DocumentDetail)
@router.post("/api/documents/text", response_model=DocumentDetail)
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


def _ingestion_response(document: Document, segment_count: int) -> DocumentIngestionResponse:
    return DocumentIngestionResponse(
        id=str(document.id),
        source_type=document.source_type,
        ingestion_status=document.ingestion_status,
        ingestion_error=document.ingestion_error,
        page_count=document.page_count,
        segment_count=segment_count,
        title=document.title,
        created_at=document.created_at,
    )


@router.post("/api/uploads/presign", response_model=PresignUploadResponse)
async def presign_upload(body: PresignUploadRequest, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)

    if body.content_type not in policy.ALLOWED_PDF_CONTENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Desteklenmeyen içerik türü: {body.content_type}")

    async with runtime.sessions() as db:
        workspace = await service.get_or_create_workspace(db, user=user, visitor_id=visitor_id)

    storage_key = f"{workspace.id}/{uuid.uuid4()}.pdf"
    try:
        storage.ensure_bucket()
        upload_url = storage.generate_presigned_upload(storage_key, content_type=body.content_type)
    except storage.StorageError as exc:
        raise HTTPException(status_code=503, detail="Depolama servisi kullanılamıyor") from exc

    return PresignUploadResponse(
        upload_url=upload_url,
        storage_key=storage_key,
        expires_in_seconds=storage.PRESIGN_EXPIRES_SECONDS,
    )


@router.post("/api/documents/pdf", response_model=DocumentIngestionResponse, status_code=status.HTTP_201_CREATED)
async def create_pdf_document(body: DocumentPdfCreateRequest, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)

    # storage_key must be the one this identity's workspace was presigned for.
    async with runtime.sessions() as db:
        workspace = await service.get_or_create_workspace(db, user=user, visitor_id=visitor_id)
        if not body.storage_key.startswith(f"{workspace.id}/"):
            raise HTTPException(status_code=403, detail="Bu storage_key bu çalışma alanına ait değil")

        info = storage.stat_object(body.storage_key)
        if info is None:
            raise HTTPException(status_code=404, detail="Yüklenmiş dosya bulunamadı")
        if info["size"] > policy.MAX_PDF_UPLOAD_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"PDF dosyası en fazla {policy.MAX_PDF_UPLOAD_BYTES} bayt olabilir",
            )

        document = await service.create_pdf_document(
            db,
            workspace=workspace,
            user=user,
            visitor_id=visitor_id,
            storage_key=body.storage_key,
            title=body.title,
        )

    try:
        worker_ingestion_tasks.ingest_pdf_document.delay(str(document.id))
    except Exception:
        logger.warning("PDF ingestion %s could not be enqueued", document.id, exc_info=True)

    return _ingestion_response(document, segment_count=0)


@router.post("/api/documents/url", response_model=DocumentIngestionResponse, status_code=status.HTTP_201_CREATED)
async def create_url_document(body: DocumentUrlCreateRequest, request: Request, response: Response):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)

    try:
        assert_public_url(body.url)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    async with runtime.sessions() as db:
        workspace = await service.get_or_create_workspace(db, user=user, visitor_id=visitor_id)
        document, created = await service.create_url_document(
            db,
            workspace=workspace,
            user=user,
            visitor_id=visitor_id,
            url=body.url,
            title=body.title,
        )
        segment_count = await service.count_segments(db, document_id=document.id)

    if created:
        try:
            worker_ingestion_tasks.ingest_url_document.delay(str(document.id))
        except Exception:
            logger.warning("URL ingestion %s could not be enqueued", document.id, exc_info=True)

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _ingestion_response(document, segment_count=segment_count)


@router.get("/api/documents/{document_id}/ingestion", response_model=DocumentIngestionResponse)
async def get_document_ingestion(document_id: str, request: Request):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_id = _parse_uuid(document_id)

    async with runtime.sessions() as db:
        document = await service.get_accessible_document(
            db, document_id=parsed_id, user=user, visitor_id=visitor_id
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Doküman bulunamadı")
        segment_count = await service.count_segments(db, document_id=document.id)

    return _ingestion_response(document, segment_count=segment_count)


def _job_summary(entry, triple_count: int) -> ExtractionJobSummary:
    job = entry.job
    return ExtractionJobSummary(
        id=str(job.id),
        document_id=str(job.document_id),
        workspace_id=str(job.workspace_id),
        document_title=entry.document_title,
        document_preview=entry.document_preview,
        document_source_type=entry.document_source_type,
        document_page_count=entry.document_page_count,
        document_source_url=entry.document_source_url,
        triple_count=triple_count,
        model=job.model,
        kg_type=job.kg_type,
        prompt_type=job.prompt_type,
        embedding_model=job.embedding_model,
        ontology_language=job.ontology_language,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/api/extraction-jobs", response_model=ExtractionJobResponse)
async def create_extraction_job(
    body: ExtractionJobCreateRequest, request: Request, response: Response
):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    document_id = _parse_uuid(body.document_id)

    try:
        policy.validate_pipeline(
            model=body.model,
            kg_type=body.kg_type,
            prompt_type=body.prompt_type,
            embedding_model=body.embedding_model,
            ontology_language=body.ontology_language,
            is_anonymous=user is None,
        )
    except policy.PolicyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    async with runtime.sessions() as db:
        document = await service.get_accessible_document(
            db, document_id=document_id, user=user, visitor_id=visitor_id
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Doküman bulunamadı")

        try:
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
        except policy.PolicyError as exc:
            # Covers both the active-job quota (429) and the document not
            # being ingestion-ready yet (409).
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if created:
        job_id = str(job.id)
        try:
            worker_tasks.run_extraction_job.delay(job_id)
        except Exception:
            # Broker unreachable at publish time: the job row stays "queued" in
            # Postgres rather than being lost, ready to be picked up by a
            # future retry sweep or a manual re-trigger.
            logger.warning("Extraction job %s could not be enqueued", job_id, exc_info=True)

    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _job_response(job)


@router.get("/api/extraction-jobs", response_model=list[ExtractionJobSummary])
async def list_extraction_jobs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: JobStatus | None = Query(default=None),
    document_id: str | None = Query(default=None),
):
    runtime = _runtime(request)
    user, visitor_id = _identity(request)
    parsed_document_id = _parse_uuid(document_id) if document_id else None

    async with runtime.sessions() as db:
        workspace = await service.get_or_create_workspace(db, user=user, visitor_id=visitor_id)
        entries = await service.list_jobs_for_workspace(
            db,
            workspace_id=workspace.id,
            limit=limit,
            offset=offset,
            status=status,
            document_id=parsed_document_id,
        )
        triple_counts = await triples_service.count_triples_by_job(
            db, job_ids=[entry.job.id for entry in entries]
        )

    return [
        _job_summary(entry, triple_counts.get(entry.job.id, 0))
        for entry in entries
    ]


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
