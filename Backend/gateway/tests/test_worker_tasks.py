from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.models import Base
from documents.models import Document, ExtractionJob, JobStatus
from extraction.errors import ExtractionError
import triples.models  # noqa: F401  (register tables on Base.metadata)
from triples.service import TripleInput, record_triples_for_job
import worker.tasks as worker_tasks
from worker.celery_app import celery_app

from _worker_support import create_document_and_job, load_job, load_triples



@pytest.fixture()
def worker_env(tmp_path: Path, monkeypatch):
    database_path = tmp_path / "worker.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(worker_tasks, "RETRY_BACKOFF_SECONDS", 0)

    engine = create_async_engine(database_url)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    asyncio.run(engine.dispose())

    celery_app.conf.task_always_eager = True
    # Eager mode only replays retries synchronously when propagation is off;
    # unexpected bugs are still caught because every test asserts on `.get()`.
    celery_app.conf.task_eager_propagates = False
    yield database_url
    celery_app.conf.task_always_eager = False


def test_run_extraction_job_success_creates_triples_and_evidence(worker_env, monkeypatch) -> None:
    database_url = worker_env
    text = "Atatürk 1881 yılında Selanik'te doğdu."
    _, job_id = create_document_and_job(database_url, text)

    async def fake_run_extraction(**kwargs):
        return [
            {
                "baş": "Atatürk",
                "baş_tipi": "Kişi",
                "ilişki": "doğum_yeri",
                "uç": "Selanik",
                "uç_tipi": "Yer",
                "kaynak_cumle": text,
            }
        ]

    monkeypatch.setattr(worker_tasks, "run_extraction", fake_run_extraction)

    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.completed
    assert job.started_at is not None
    assert job.completed_at is not None
    assert job.result == {"triple_count": 1}

    stored = load_triples(database_url, job_id)
    assert len(stored) == 1
    assert stored[0].subject == "Atatürk"
    assert stored[0].obj == "Selanik"
    assert stored[0].evidence[0].char_start == 0
    assert stored[0].evidence[0].char_end == len(text)


def test_run_extraction_job_is_noop_once_completed(worker_env, monkeypatch) -> None:
    database_url = worker_env
    text = "Tekrar teslim edilen mesaj testi."
    _, job_id = create_document_and_job(database_url, text)

    async def fake_run_extraction(**kwargs):
        return [{"baş": "A", "ilişki": "rel", "uç": "B", "kaynak_cumle": text}]

    monkeypatch.setattr(worker_tasks, "run_extraction", fake_run_extraction)
    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)
    assert load_job(database_url, job_id).status == JobStatus.completed

    called = {"value": False}

    async def should_not_run(**kwargs):
        called["value"] = True
        return []

    monkeypatch.setattr(worker_tasks, "run_extraction", should_not_run)
    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)

    assert called["value"] is False
    assert len(load_triples(database_url, job_id)) == 1


def test_run_extraction_job_replaces_stale_triples_instead_of_duplicating(
    worker_env, monkeypatch
) -> None:
    database_url = worker_env
    text = "Yeniden işlem testi metni."
    document_id, job_id = create_document_and_job(database_url, text)

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def seed_stale_attempt() -> None:
        async with sessions() as db:
            job = await db.get(ExtractionJob, uuid.UUID(job_id))
            document = await db.get(Document, uuid.UUID(document_id))
            job.status = JobStatus.running
            await db.commit()
            await record_triples_for_job(
                db,
                job=job,
                document=document,
                triples=[TripleInput(subject="Eski", predicate="rel", object="Değer")],
            )

    asyncio.run(seed_stale_attempt())
    asyncio.run(engine.dispose())
    assert len(load_triples(database_url, job_id)) == 1

    async def fake_run_extraction(**kwargs):
        return [{"baş": "Yeni", "ilişki": "rel", "uç": "Sonuç", "kaynak_cumle": text}]

    monkeypatch.setattr(worker_tasks, "run_extraction", fake_run_extraction)
    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)

    stored = load_triples(database_url, job_id)
    assert len(stored) == 1
    assert stored[0].subject == "Yeni"
    assert load_job(database_url, job_id).status == JobStatus.completed


def test_run_extraction_job_marks_failed_on_non_retryable_error(worker_env, monkeypatch) -> None:
    database_url = worker_env
    _, job_id = create_document_and_job(database_url, "Hata testi metni.")

    async def failing(**kwargs):
        raise ExtractionError("Bilinmeyen kg_type", status_code=400, retryable=False)

    monkeypatch.setattr(worker_tasks, "run_extraction", failing)
    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.failed
    assert job.error_message == "Bilinmeyen kg_type"
    assert job.completed_at is not None
    assert load_triples(database_url, job_id) == []


def test_run_extraction_job_fails_after_exhausting_retries(worker_env, monkeypatch) -> None:
    database_url = worker_env
    _, job_id = create_document_and_job(database_url, "Tekrar deneme testi.")

    call_count = {"n": 0}

    async def always_fails(**kwargs):
        call_count["n"] += 1
        raise ExtractionError("Geçici hata", status_code=502, retryable=True)

    monkeypatch.setattr(worker_tasks, "run_extraction", always_fails)
    monkeypatch.setattr(worker_tasks.run_extraction_job, "max_retries", 1)

    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.failed
    assert job.error_message == "Geçici hata"
    assert call_count["n"] >= 2


def test_run_extraction_job_recovers_after_transient_failure(worker_env, monkeypatch) -> None:
    database_url = worker_env
    text = "Geçici hata sonrası başarı testi."
    _, job_id = create_document_and_job(database_url, text)

    attempts = {"n": 0}

    async def flaky(**kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ExtractionError("Geçici hata", status_code=502, retryable=True)
        return [{"baş": "A", "ilişki": "rel", "uç": "B", "kaynak_cumle": text}]

    monkeypatch.setattr(worker_tasks, "run_extraction", flaky)
    worker_tasks.run_extraction_job.delay(job_id).get(propagate=True)

    job = load_job(database_url, job_id)
    assert job.status == JobStatus.completed
    assert attempts["n"] == 2
    assert len(load_triples(database_url, job_id)) == 1
