from __future__ import annotations

import asyncio
import logging
import os
import uuid

from celery.exceptions import Retry
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from accounts.models import utc_now
from documents.models import Document, ExtractionJob, JobStatus
from extraction import ExtractionError, run_extraction
from triples.service import build_triple_inputs_from_raw, replace_triples_for_job

from .celery_app import celery_app
from .db import build_session_factory

logger = logging.getLogger(__name__)

MAX_RETRIES = int(os.getenv("EXTRACTION_JOB_MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = int(os.getenv("EXTRACTION_JOB_RETRY_BACKOFF_SECONDS", "30"))


class _RetryableFailure(Exception):
    def __init__(self, original: Exception, safe_message: str):
        super().__init__(safe_message)
        self.original = original
        self.safe_message = safe_message


async def _claim_job(
    sessions: async_sessionmaker, job_id: uuid.UUID
) -> tuple[ExtractionJob, Document] | None:
    """Atomically flips queued -> running. Returns None if another worker
    already claimed it, or if it's already completed/failed (idempotent no-op
    for redelivered/duplicate messages)."""
    async with sessions() as db:
        job = await db.get(ExtractionJob, job_id)
        if job is None or job.status in (JobStatus.completed, JobStatus.failed):
            return None

        if job.status == JobStatus.queued:
            result = await db.execute(
                update(ExtractionJob)
                .where(ExtractionJob.id == job_id, ExtractionJob.status == JobStatus.queued)
                .values(status=JobStatus.running, started_at=utc_now())
            )
            await db.commit()
            if result.rowcount == 0:
                return None
            await db.refresh(job)

        document = await db.get(Document, job.document_id)
        return job, document


async def _mark_failed(sessions: async_sessionmaker, job_id: uuid.UUID, error_message: str) -> None:
    async with sessions() as db:
        job = await db.get(ExtractionJob, job_id)
        if job is None:
            return
        job.status = JobStatus.failed
        job.error_message = error_message[:2000]
        job.completed_at = utc_now()
        await db.commit()


async def _mark_completed(
    sessions: async_sessionmaker, job_id: uuid.UUID, raw_triplets: list[dict]
) -> int:
    async with sessions() as db:
        job = await db.get(ExtractionJob, job_id)
        document = await db.get(Document, job.document_id)
        triple_inputs = build_triple_inputs_from_raw(raw_triplets, document.normalized_text)
        created = await replace_triples_for_job(db, job=job, document=document, triples=triple_inputs)
        job.status = JobStatus.completed
        job.result = {"triple_count": len(created)}
        job.error_message = None
        job.completed_at = utc_now()
        await db.commit()
        return len(created)


async def _process_job(job_id: uuid.UUID) -> None:
    engine, sessions = build_session_factory()
    try:
        claimed = await _claim_job(sessions, job_id)
        if claimed is None:
            return
        job, document = claimed

        try:
            raw_triplets = await run_extraction(
                text=document.normalized_text,
                model=job.model,
                kg_type=job.kg_type,
                prompt_type=job.prompt_type,
                embedding_model=job.embedding_model,
                ontology_language=job.ontology_language,
                request_id=f"job:{job_id}",
            )
        except ExtractionError as exc:
            if exc.retryable:
                raise _RetryableFailure(exc, exc.message) from exc
            await _mark_failed(sessions, job_id, exc.message)
            return
        except Exception as exc:  # pragma: no cover - defensive catch-all
            logger.exception("Unexpected extraction failure for job %s", job_id)
            raise _RetryableFailure(exc, "Beklenmeyen bir hata oluştu") from exc

        await _mark_completed(sessions, job_id, raw_triplets)
    finally:
        await engine.dispose()


async def _mark_failed_standalone(job_id: uuid.UUID, error_message: str) -> None:
    engine, sessions = build_session_factory()
    try:
        await _mark_failed(sessions, job_id, error_message)
    finally:
        await engine.dispose()


@celery_app.task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=RETRY_BACKOFF_SECONDS)
def run_extraction_job(self, job_id: str) -> None:
    """Celery entrypoint. Receives only the job_id; everything else (model,
    kg_type, prompt_type, ...) is read from the extraction_jobs row so the
    broker never carries pipeline parameters or document text."""
    try:
        asyncio.run(_process_job(uuid.UUID(job_id)))
    except _RetryableFailure as exc:
        try:
            raise self.retry(exc=exc.original, countdown=RETRY_BACKOFF_SECONDS)
        except Retry:
            # Retries remain: let Celery reschedule this task.
            raise
        except Exception:
            # self.retry() re-raises the original exception once max_retries
            # is exhausted instead of a distinct "exceeded" error.
            asyncio.run(_mark_failed_standalone(uuid.UUID(job_id), exc.safe_message))
