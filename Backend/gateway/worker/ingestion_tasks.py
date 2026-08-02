from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid

from celery.exceptions import Retry
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

import policy
import storage
from documents import service as documents_service
from documents.models import Document, IngestionStatus
from ingestion.errors import IngestionError
# Module-reference imports (not `from ingestion.pdf import extract_pdf`): if
# something imports `ingestion.url_fetch` directly first, that module is
# still mid-initialization when it (transitively, via documents -> routes ->
# worker.ingestion_tasks) reaches back here, and a name-pull import would
# fail with "cannot import name ... from partially initialized module".
# Referencing the module object itself always succeeds. See
# documents/routes.py for the same pattern with worker.tasks.
from ingestion import pdf as ingestion_pdf
from ingestion import url_fetch as ingestion_url_fetch

from .celery_app import celery_app
from .db import build_session_factory

logger = logging.getLogger(__name__)

INGESTION_MAX_RETRIES = int(os.getenv("INGESTION_MAX_RETRIES", "2"))
INGESTION_RETRY_BACKOFF_SECONDS = int(os.getenv("INGESTION_RETRY_BACKOFF_SECONDS", "20"))


class _RetryableIngestionFailure(Exception):
    def __init__(self, original: Exception, safe_message: str):
        super().__init__(safe_message)
        self.original = original
        self.safe_message = safe_message


async def _claim_document(
    sessions: async_sessionmaker, document_id: uuid.UUID
) -> Document | None:
    """Atomically flips pending -> processing. Returns None if another
    worker already claimed it, or if it's already ready/failed (idempotent
    no-op for redelivered/duplicate messages)."""
    async with sessions() as db:
        document = await db.get(Document, document_id)
        if document is None or document.ingestion_status in (
            IngestionStatus.ready, IngestionStatus.failed,
        ):
            return None

        if document.ingestion_status == IngestionStatus.pending:
            result = await db.execute(
                update(Document)
                .where(Document.id == document_id, Document.ingestion_status == IngestionStatus.pending)
                .values(ingestion_status=IngestionStatus.processing, ingestion_error=None)
            )
            await db.commit()
            if result.rowcount == 0:
                return None
            await db.refresh(document)

        return document


async def _mark_failed(sessions: async_sessionmaker, document_id: uuid.UUID, message: str) -> None:
    async with sessions() as db:
        document = await db.get(Document, document_id)
        if document is None:
            return
        await documents_service.mark_ingestion_failed(db, document=document, error_message=message)


async def _mark_failed_standalone(document_id: uuid.UUID, message: str) -> None:
    engine, sessions = build_session_factory()
    try:
        await _mark_failed(sessions, document_id, message)
    finally:
        await engine.dispose()


async def _finish_ready(
    sessions: async_sessionmaker,
    document_id: uuid.UUID,
    *,
    raw_text: str,
    normalized_text: str,
    page_count: int | None,
    file_hash: str | None,
    segments,
) -> None:
    async with sessions() as db:
        document = await db.get(Document, document_id)
        await documents_service.replace_segments_for_document(db, document=document, segments=segments)
        await documents_service.mark_ingestion_ready(
            db,
            document=document,
            raw_text=raw_text,
            normalized_text=normalized_text,
            page_count=page_count,
            file_hash=file_hash,
        )


async def _process_pdf(document_id: uuid.UUID) -> None:
    engine, sessions = build_session_factory()
    try:
        document = await _claim_document(sessions, document_id)
        if document is None:
            return

        try:
            pdf_bytes = storage.get_object_bytes(document.storage_key)
        except storage.StorageError as exc:
            raise _RetryableIngestionFailure(exc, "PDF dosyasına depolamadan erişilemedi") from exc

        if len(pdf_bytes) > policy.MAX_PDF_UPLOAD_BYTES:
            await _mark_failed(
                sessions, document_id,
                f"PDF dosyası en fazla {policy.MAX_PDF_UPLOAD_BYTES} bayt olabilir",
            )
            return

        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

        try:
            full_text, segments, page_count = ingestion_pdf.extract_pdf(pdf_bytes)
        except IngestionError as exc:
            if exc.retryable:
                raise _RetryableIngestionFailure(exc, exc.message) from exc
            await _mark_failed(sessions, document_id, exc.message)
            return
        except Exception as exc:  # pragma: no cover - defensive catch-all
            logger.exception("Unexpected PDF ingestion failure for document %s", document_id)
            raise _RetryableIngestionFailure(exc, "Beklenmeyen bir hata oluştu") from exc

        try:
            # PDF has no separate "user-typed raw" text distinct from what
            # was extracted, so raw_text and normalized_text are the same
            # string here (unlike the plain-text upload path).
            await _finish_ready(
                sessions, document_id,
                raw_text=full_text, normalized_text=full_text,
                page_count=page_count, file_hash=file_hash, segments=segments,
            )
        except policy.PolicyError as exc:
            await _mark_failed(sessions, document_id, exc.message)
    finally:
        await engine.dispose()


async def _process_url(document_id: uuid.UUID) -> None:
    engine, sessions = build_session_factory()
    try:
        document = await _claim_document(sessions, document_id)
        if document is None:
            return

        try:
            normalized_text, segments, _final_url = await ingestion_url_fetch.ingest_url(document.source_url)
        except IngestionError as exc:
            if exc.retryable:
                raise _RetryableIngestionFailure(exc, exc.message) from exc
            await _mark_failed(sessions, document_id, exc.message)
            return
        except Exception as exc:  # pragma: no cover - defensive catch-all
            logger.exception("Unexpected URL ingestion failure for document %s", document_id)
            raise _RetryableIngestionFailure(exc, "Beklenmeyen bir hata oluştu") from exc

        file_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        try:
            await _finish_ready(
                sessions, document_id,
                raw_text=normalized_text, normalized_text=normalized_text,
                page_count=None, file_hash=file_hash, segments=segments,
            )
        except policy.PolicyError as exc:
            await _mark_failed(sessions, document_id, exc.message)
    finally:
        await engine.dispose()


@celery_app.task(
    bind=True, max_retries=INGESTION_MAX_RETRIES, default_retry_delay=INGESTION_RETRY_BACKOFF_SECONDS
)
def ingest_pdf_document(self, document_id: str) -> None:
    try:
        asyncio.run(_process_pdf(uuid.UUID(document_id)))
    except _RetryableIngestionFailure as exc:
        try:
            raise self.retry(exc=exc.original, countdown=INGESTION_RETRY_BACKOFF_SECONDS)
        except Retry:
            raise
        except Exception:
            asyncio.run(_mark_failed_standalone(uuid.UUID(document_id), exc.safe_message))


@celery_app.task(
    bind=True, max_retries=INGESTION_MAX_RETRIES, default_retry_delay=INGESTION_RETRY_BACKOFF_SECONDS
)
def ingest_url_document(self, document_id: str) -> None:
    try:
        asyncio.run(_process_url(uuid.UUID(document_id)))
    except _RetryableIngestionFailure as exc:
        try:
            raise self.retry(exc=exc.original, countdown=INGESTION_RETRY_BACKOFF_SECONDS)
        except Retry:
            raise
        except Exception:
            asyncio.run(_mark_failed_standalone(uuid.UUID(document_id), exc.safe_message))
