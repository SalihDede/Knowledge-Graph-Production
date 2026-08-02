from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.database import create_database
from accounts.models import Base, utc_now
from documents.models import ExtractionJob, JobStatus
import triples.models  # noqa: F401  (register tables on Base.metadata)
import worker.recovery as recovery

from _worker_support import create_document_and_job, load_job

POSTGRES_TEST_URL = os.getenv(
    "POSTGRES_TEST_URL",
    "postgresql+asyncpg://kg:kg@localhost:55432/kg_recovery_test",
)


def _postgres_reachable() -> bool:
    async def ping() -> bool:
        # asyncpg wants a plain postgresql:// DSN, not the +asyncpg driver suffix.
        dsn = POSTGRES_TEST_URL.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn, timeout=1)
        await conn.close()
        return True

    try:
        return asyncio.run(ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason=(
        f"PostgreSQL is not reachable at {POSTGRES_TEST_URL} "
        "(set POSTGRES_TEST_URL to point at a real database)"
    ),
)


@pytest.fixture()
def postgres_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", POSTGRES_TEST_URL)
    monkeypatch.setattr(recovery, "QUEUED_JOB_STALE_SECONDS", 120)
    monkeypatch.setattr(recovery, "RUNNING_JOB_STALE_SECONDS", 600)
    monkeypatch.setattr(recovery, "JOB_RECOVERY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(recovery, "JOB_RECOVERY_BATCH_SIZE", 100)

    engine = create_async_engine(POSTGRES_TEST_URL)

    async def reset_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(reset_schema())
    asyncio.run(engine.dispose())
    return POSTGRES_TEST_URL


def _mutate_job(database_url: str, job_id: str, **values) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

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


def test_recovers_a_stale_job_against_real_postgres(postgres_env) -> None:
    database_url = postgres_env
    _, job_id = create_document_and_job(database_url, "Gerçek Postgres testi.")
    stale_created_at = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
    _mutate_job(database_url, job_id, created_at=stale_created_at)

    async def scenario() -> dict:
        _, sessions = create_database(database_url)
        return await recovery.sweep_stale_jobs(sessions)

    result = asyncio.run(scenario())

    assert [str(x) for x in result["requeued"]] == [job_id]
    job = load_job(database_url, job_id)
    assert job.status == JobStatus.queued
    assert job.recovery_attempts == 1


def test_row_lock_prevents_a_second_scheduler_from_double_recovering(postgres_env) -> None:
    """Two Celery Beat replicas could fire the same sweep at once. FOR UPDATE
    SKIP LOCKED must ensure only one of them ever recovers a given job."""
    database_url = postgres_env
    _, job_id = create_document_and_job(database_url, "İki scheduler yarışı.")
    stale_created_at = utc_now() - timedelta(seconds=recovery.QUEUED_JOB_STALE_SECONDS + 30)
    _mutate_job(database_url, job_id, created_at=stale_created_at)

    async def scenario():
        engine_a = create_async_engine(database_url)
        sessions_a = async_sessionmaker(engine_a, expire_on_commit=False)

        async with sessions_a() as db_a:
            # Simulates "scheduler A" having already locked this row inside
            # its own sweep transaction, without having committed yet.
            await db_a.execute(
                select(ExtractionJob.id)
                .where(ExtractionJob.id == uuid.UUID(job_id))
                .with_for_update()
            )

            engine_b, sessions_b = create_database(database_url)
            try:
                # "scheduler B" runs a full, independent sweep concurrently.
                result_b = await recovery.sweep_stale_jobs(sessions_b)
            finally:
                await engine_b.dispose()

            await db_a.rollback()

        await engine_a.dispose()
        return result_b

    result_b = asyncio.run(scenario())

    assert result_b == {"requeued": [], "failed": []}
    # Untouched while scheduler A held the lock.
    job = load_job(database_url, job_id)
    assert job.status == JobStatus.queued
    assert job.recovery_attempts == 0

    # Once the lock is released, a fresh sweep recovers it exactly once.
    async def final_sweep() -> dict:
        _, sessions = create_database(database_url)
        return await recovery.sweep_stale_jobs(sessions)

    result_final = asyncio.run(final_sweep())
    assert [str(x) for x in result_final["requeued"]] == [job_id]
    assert load_job(database_url, job_id).recovery_attempts == 1
