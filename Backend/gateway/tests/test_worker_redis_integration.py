from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
import redis as redis_sync
from celery.contrib.testing.worker import start_worker
from sqlalchemy.ext.asyncio import create_async_engine

from accounts.models import Base
from documents.models import JobStatus
import triples.models  # noqa: F401  (register tables on Base.metadata)
import worker.tasks as worker_tasks
from worker.celery_app import celery_app

from _worker_support import create_document_and_job, load_job, load_triples

REDIS_TEST_URL = os.getenv("REDIS_TEST_URL", "redis://localhost:6399/15")


def _redis_reachable() -> bool:
    try:
        client = redis_sync.Redis.from_url(REDIS_TEST_URL, socket_connect_timeout=1)
        return bool(client.ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason=f"Redis is not reachable at {REDIS_TEST_URL} (set REDIS_TEST_URL to point at a real broker)",
)


@pytest.fixture()
def redis_worker_env(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "worker_redis.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(worker_tasks, "RETRY_BACKOFF_SECONDS", 0)

    engine = create_async_engine(database_url)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        # Flush any leftovers from a previous interrupted run on this Redis DB.
        client = redis_sync.Redis.from_url(REDIS_TEST_URL)
        client.flushdb()

    asyncio.run(prepare())
    asyncio.run(engine.dispose())

    original_broker_url = celery_app.conf.broker_url
    celery_app.conf.broker_url = REDIS_TEST_URL
    celery_app.conf.task_always_eager = False
    yield database_url
    celery_app.conf.broker_url = original_broker_url


def test_real_redis_broker_delivers_and_completes_job(redis_worker_env, monkeypatch) -> None:
    database_url = redis_worker_env
    text = "Gerçek Redis üzerinden işlenen doküman."
    _, job_id = create_document_and_job(database_url, text)

    async def fake_run_extraction(**kwargs):
        return [{"baş": "A", "ilişki": "rel", "uç": "B", "kaynak_cumle": text}]

    monkeypatch.setattr(worker_tasks, "run_extraction", fake_run_extraction)

    with start_worker(celery_app, pool="solo", loglevel="info", perform_ping_check=False):
        worker_tasks.run_extraction_job.delay(job_id)

        deadline = time.monotonic() + 15
        job = load_job(database_url, job_id)
        while job.status not in (JobStatus.completed, JobStatus.failed) and time.monotonic() < deadline:
            time.sleep(0.2)
            job = load_job(database_url, job_id)

    assert job.status == JobStatus.completed
    assert job.result == {"triple_count": 1}
    assert len(load_triples(database_url, job_id)) == 1
