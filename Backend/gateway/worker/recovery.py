from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from accounts.models import utc_now
from documents.models import ExtractionJob, JobStatus

logger = logging.getLogger(__name__)

QUEUED_JOB_STALE_SECONDS = int(os.getenv("QUEUED_JOB_STALE_SECONDS", "120"))
RUNNING_JOB_STALE_SECONDS = int(os.getenv("RUNNING_JOB_STALE_SECONDS", "600"))
JOB_RECOVERY_MAX_ATTEMPTS = int(os.getenv("JOB_RECOVERY_MAX_ATTEMPTS", "3"))
JOB_RECOVERY_BATCH_SIZE = int(os.getenv("JOB_RECOVERY_BATCH_SIZE", "100"))

RECOVERY_EXHAUSTED_MESSAGE = "Job kurtarma denemeleri tükendi; işlem güvenli şekilde durduruldu."


async def _select_stale_ids(
    db, *, status: JobStatus, reference_column, stale_before, batch_size: int
) -> list[tuple[uuid.UUID, int]]:
    """Locks up to `batch_size` stale rows so a concurrently running sweep
    (another beat tick, another scheduler replica) skips them instead of
    racing to recover the same job twice. No-op lock on SQLite (used in unit
    tests); a real `FOR UPDATE SKIP LOCKED` on PostgreSQL."""
    stale_column = func.coalesce(ExtractionJob.last_recovery_at, reference_column)
    result = await db.execute(
        select(ExtractionJob.id, ExtractionJob.recovery_attempts)
        .where(ExtractionJob.status == status, stale_column < stale_before)
        .order_by(ExtractionJob.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(result.all())


async def _apply_recovery(
    db, rows: list[tuple[uuid.UUID, int]], *, sweep_id: uuid.UUID, from_status: JobStatus
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    to_requeue: list[uuid.UUID] = []
    to_fail: list[uuid.UUID] = []

    for job_id, recovery_attempts in rows:
        if recovery_attempts + 1 > JOB_RECOVERY_MAX_ATTEMPTS:
            to_fail.append(job_id)
        else:
            to_requeue.append(job_id)

    now = utc_now()

    if to_requeue:
        await db.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id.in_(to_requeue))
            .values(
                status=JobStatus.queued,
                started_at=None,
                recovery_attempts=ExtractionJob.recovery_attempts + 1,
                last_recovery_at=now,
            )
        )
        for job_id in to_requeue:
            logger.info(
                "[recovery:%s] job %s recovered from %s, re-enqueuing",
                sweep_id, job_id, from_status.value,
            )

    if to_fail:
        await db.execute(
            update(ExtractionJob)
            .where(ExtractionJob.id.in_(to_fail))
            .values(
                status=JobStatus.failed,
                error_message=RECOVERY_EXHAUSTED_MESSAGE,
                recovery_attempts=ExtractionJob.recovery_attempts + 1,
                last_recovery_at=now,
                completed_at=now,
            )
        )
        for job_id in to_fail:
            logger.warning(
                "[recovery:%s] job %s exceeded %s recovery attempts from %s, marking failed",
                sweep_id, job_id, JOB_RECOVERY_MAX_ATTEMPTS, from_status.value,
            )

    return to_requeue, to_fail


async def sweep_stale_jobs(sessions: async_sessionmaker) -> dict[str, list[uuid.UUID]]:
    """One recovery pass over stale jobs:

    - `queued` jobs whose Celery message may never have been published
      (broker was unreachable at creation time) are re-enqueued as-is.
    - `running` jobs whose worker likely crashed mid-task are reset to
      `queued` (clearing `started_at`) and re-enqueued.

    Both categories share the same per-job `recovery_attempts` counter and
    `JOB_RECOVERY_MAX_ATTEMPTS` cap; a job that keeps failing to make
    progress is marked `failed` instead of being recovered forever.

    Returns job ids to (re-)dispatch to Celery. Dispatch happens *after* this
    function's transaction commits, so the caller does the actual
    `.delay(...)` calls once the returned ids are final.
    """
    sweep_id = uuid.uuid4()
    now = utc_now()
    queued_before = now - timedelta(seconds=QUEUED_JOB_STALE_SECONDS)
    running_before = now - timedelta(seconds=RUNNING_JOB_STALE_SECONDS)

    async with sessions() as db:
        queued_rows = await _select_stale_ids(
            db,
            status=JobStatus.queued,
            reference_column=ExtractionJob.created_at,
            stale_before=queued_before,
            batch_size=JOB_RECOVERY_BATCH_SIZE,
        )
        running_rows = await _select_stale_ids(
            db,
            status=JobStatus.running,
            reference_column=ExtractionJob.started_at,
            stale_before=running_before,
            batch_size=JOB_RECOVERY_BATCH_SIZE,
        )

        queued_requeued, queued_failed = await _apply_recovery(
            db, queued_rows, sweep_id=sweep_id, from_status=JobStatus.queued
        )
        running_requeued, running_failed = await _apply_recovery(
            db, running_rows, sweep_id=sweep_id, from_status=JobStatus.running
        )

        await db.commit()

    requeued = queued_requeued + running_requeued
    failed = queued_failed + running_failed
    if requeued or failed:
        logger.info(
            "[recovery:%s] sweep complete: %s requeued, %s failed",
            sweep_id, len(requeued), len(failed),
        )

    return {"requeued": requeued, "failed": failed}
