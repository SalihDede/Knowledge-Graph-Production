from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.models import Base, utc_now
from documents.models import ExtractionJob, JobStatus
import triples.models  # noqa: F401  (register tables on Base.metadata)
import worker.recovery as recovery

from _worker_support import create_document_and_job, load_job


@pytest.fixture()
def recovery_env(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "recovery.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    monkeypatch.setattr(recovery, "QUEUED_JOB_STALE_SECONDS", 120)
    monkeypatch.setattr(recovery, "RUNNING_JOB_STALE_SECONDS", 600)
    monkeypatch.setattr(recovery, "JOB_RECOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(recovery, "JOB_RECOVERY_BATCH_SIZE", 100)

    engine = create_async_engine(database_url)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    asyncio.run(engine.dispose())
    return database_url


def _session_factory(database_url: str) -> async_sessionmaker:
    engine = create_async_engine(database_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _mutate_job(database_url: str, job_id: str, **values) -> None:
    engine, sessions = _session_factory(database_url)

    async def scenario() -> None:
        async with sessions() as db:
            job = await db.get(ExtractionJob, uuid.UUID(job_id))
            for key, value in values.items():
                setattr(job, key, value)
            await db.commit()

    try:
        asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())


def _run_sweep(database_url: str) -> dict:
    engine, sessions = _session_factory(database_url)

    async def scenario() -> dict:
        return await recovery.sweep_stale_jobs(sessions)

    try:
        return asyncio.run(scenario())
    finally:
        asyncio.run(engine.dispose())


def test_fresh_queued_job_is_left_alone(recovery_env) -> None:
    database_url = recovery_env
    _, job_id = create_document_and_job(database_url, "Taze job.")

    result = _run_sweep(database_url)

    assert result == {"requeued": [], "failed": []}
    job = load_job(database_url, job_id)
    assert job.status == JobStatus.queued
    assert job.recovery_attempts == 0
    assert job.last_recovery_at is None


def test_stale_queued_job_is_requeued(recovery_env) -> None:
    database_url = recovery_env
    _, job_id = create_document_and_job(database_url, "Kaybolmuş job.")
    stale_created_at = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
    _mutate_job(database_url, job_id, created_at=stale_created_at)

    result = _run_sweep(database_url)

    assert [str(job_id_) for job_id_ in result["requeued"]] == [job_id]
    assert result["failed"] == []

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.queued
    assert job.recovery_attempts == 1
    assert job.last_recovery_at is not None


def test_stale_running_job_is_reset_to_queued(recovery_env) -> None:
    database_url = recovery_env
    _, job_id = create_document_and_job(database_url, "Çökmüş worker job'ı.")
    stale_started_at = utc_now() - timedelta(seconds=recovery.RUNNING_JOB_STALE_SECONDS + 30)
    _mutate_job(database_url, job_id, status=JobStatus.running, started_at=stale_started_at)

    result = _run_sweep(database_url)

    assert [str(job_id_) for job_id_ in result["requeued"]] == [job_id]
    job = load_job(database_url, job_id)
    assert job.status == JobStatus.queued
    assert job.started_at is None
    assert job.recovery_attempts == 1


def test_recently_started_running_job_is_left_alone(recovery_env) -> None:
    database_url = recovery_env
    _, job_id = create_document_and_job(database_url, "Yeni başlamış job.")
    _mutate_job(database_url, job_id, status=JobStatus.running, started_at=utc_now())

    result = _run_sweep(database_url)

    assert result == {"requeued": [], "failed": []}
    job = load_job(database_url, job_id)
    assert job.status == JobStatus.running


def test_job_exhausting_max_attempts_is_marked_failed(recovery_env) -> None:
    database_url = recovery_env
    _, job_id = create_document_and_job(database_url, "Israrla bozuk job.")
    stale_created_at = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
    _mutate_job(
        database_url, job_id,
        created_at=stale_created_at,
        recovery_attempts=recovery.JOB_RECOVERY_MAX_ATTEMPTS,
    )

    result = _run_sweep(database_url)

    assert result["requeued"] == []
    assert [str(job_id_) for job_id_ in result["failed"]] == [job_id]

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.failed
    assert job.error_message == recovery.RECOVERY_EXHAUSTED_MESSAGE
    assert job.recovery_attempts == recovery.JOB_RECOVERY_MAX_ATTEMPTS + 1
    assert job.completed_at is not None


def test_repeated_recovery_eventually_fails_the_job(recovery_env) -> None:
    database_url = recovery_env
    _, job_id = create_document_and_job(database_url, "Tekrar tekrar takılan job.")

    for _ in range(recovery.JOB_RECOVERY_MAX_ATTEMPTS + 1):
        job = load_job(database_url, job_id)
        stale_reference = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
        _mutate_job(
            database_url, job_id,
            created_at=stale_reference,
            last_recovery_at=stale_reference if job.recovery_attempts else None,
        )
        _run_sweep(database_url)

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.failed
    assert job.recovery_attempts == recovery.JOB_RECOVERY_MAX_ATTEMPTS + 1


def test_batch_size_limits_jobs_processed_per_sweep(recovery_env, monkeypatch) -> None:
    database_url = recovery_env
    monkeypatch.setattr(recovery, "JOB_RECOVERY_BATCH_SIZE", 2)

    job_ids = []
    for index in range(3):
        _, job_id = create_document_and_job(database_url, f"Toplu iş {index}.", model=f"model-{index}")
        stale_created_at = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
        _mutate_job(database_url, job_id, created_at=stale_created_at)
        job_ids.append(job_id)

    result = _run_sweep(database_url)

    assert len(result["requeued"]) == 2
    remaining = [jid for jid in job_ids if jid not in {str(x) for x in result["requeued"]}]
    assert len(remaining) == 1
    untouched_job = load_job(database_url, remaining[0])
    assert untouched_job.recovery_attempts == 0


def test_does_not_touch_completed_or_failed_jobs(recovery_env) -> None:
    database_url = recovery_env
    _, completed_id = create_document_and_job(database_url, "Tamamlanmış iş.")
    _, failed_id = create_document_and_job(database_url, "Başarısız iş.", model="other-model")

    stale_created_at = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
    _mutate_job(database_url, completed_id, status=JobStatus.completed, created_at=stale_created_at)
    _mutate_job(database_url, failed_id, status=JobStatus.failed, created_at=stale_created_at)

    result = _run_sweep(database_url)

    assert result == {"requeued": [], "failed": []}
    assert load_job(database_url, completed_id).status == JobStatus.completed
    assert load_job(database_url, failed_id).status == JobStatus.failed
