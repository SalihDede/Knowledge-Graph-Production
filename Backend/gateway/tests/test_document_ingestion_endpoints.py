from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.config import AuthSettings
from accounts.middleware import IdentityMiddleware
from accounts.models import Base
from accounts.routes import router as auth_router
from accounts.runtime import AuthRuntime
import documents.models  # noqa: F401  (register tables on Base.metadata)
from documents.models import IngestionStatus
from documents.routes import router as documents_router
import documents.routes as documents_routes
from fakes import MemorySessionStore


def _build_documents_app(tmp_path: Path):
    database_path = tmp_path / "documents.sqlite3"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}", connect_args={"timeout": 30}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = AuthSettings(
        enabled=True,
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url="redis://unused",
        cookie_secret="test-cookie-secret-that-is-long-enough",
        cookie_secure=False,
        cookie_domain=None,
        session_ttl_seconds=3600,
        visitor_ttl_seconds=86400,
    )
    store = MemorySessionStore()
    runtime = AuthRuntime(
        settings=settings,
        engine=engine,
        sessions=sessions,
        session_store=store,
        visitor_signer=URLSafeTimedSerializer(settings.cookie_secret),
    )

    async def prepare_database():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())

    app = FastAPI()
    app.state.accounts = runtime
    app.add_middleware(IdentityMiddleware, runtime=runtime)
    app.include_router(auth_router)
    app.include_router(documents_router)
    return app, runtime, engine


@pytest.fixture()
def ingestion_app(tmp_path: Path, monkeypatch):
    # No real MinIO/Celery/Redis in the test environment -- stub the
    # storage + Celery dispatch boundaries and exercise the HTTP/service
    # layer above them.
    monkeypatch.setattr(documents_routes.worker_tasks.run_extraction_job, "delay", lambda *a, **kw: None)
    monkeypatch.setattr(documents_routes.worker_ingestion_tasks.ingest_pdf_document, "delay", lambda *a, **kw: None)
    monkeypatch.setattr(documents_routes.worker_ingestion_tasks.ingest_url_document, "delay", lambda *a, **kw: None)
    monkeypatch.setattr("catalog.registry.is_model_allowed", lambda *a, **kw: True)

    app, runtime, engine = _build_documents_app(tmp_path)
    yield app, runtime
    asyncio.run(engine.dispose())


def test_presign_upload_returns_workspace_scoped_key(ingestion_app, monkeypatch) -> None:
    monkeypatch.setattr(documents_routes.storage, "ensure_bucket", lambda: None)
    monkeypatch.setattr(
        documents_routes.storage, "generate_presigned_upload",
        lambda key, *, content_type: f"http://minio.test/{key}?signed=1",
    )

    app, _ = ingestion_app
    with TestClient(app) as client:
        response = client.post("/api/uploads/presign", json={"filename": "doc.pdf"})

    assert response.status_code == 200
    body = response.json()
    assert body["storage_key"].endswith(".pdf")
    assert body["upload_url"].startswith("http://minio.test/")
    assert "expires_in_seconds" in body


def test_presign_upload_rejects_disallowed_content_type(ingestion_app) -> None:
    app, _ = ingestion_app
    with TestClient(app) as client:
        response = client.post(
            "/api/uploads/presign", json={"filename": "doc.txt", "content_type": "text/plain"}
        )

    assert response.status_code == 422


def test_create_pdf_document_rejects_foreign_storage_key(ingestion_app) -> None:
    app, _ = ingestion_app
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/pdf",
            json={"storage_key": f"{uuid.uuid4()}/other-workspace.pdf", "title": "Hijack"},
        )

    assert response.status_code == 403


def test_create_pdf_document_requires_uploaded_object(ingestion_app, monkeypatch) -> None:
    monkeypatch.setattr(documents_routes.storage, "stat_object", lambda key: None)

    app, _ = ingestion_app
    with TestClient(app) as client:
        # workspace id isn't directly exposed via /api/auth/me; derive it
        # from a created text document instead (same identity/cookie jar).
        doc = client.post("/api/documents/text", json={"text": "for workspace id"}).json()
        storage_key = f"{doc['workspace_id']}/missing.pdf"
        response = client.post(
            "/api/documents/pdf", json={"storage_key": storage_key, "title": "Missing"}
        )

    assert response.status_code == 404


def test_create_pdf_document_rejects_oversized_upload(ingestion_app, monkeypatch) -> None:
    monkeypatch.setattr(documents_routes.storage, "stat_object", lambda key: {"size": 10**9})

    with TestClient(ingestion_app[0]) as client:
        doc = client.post("/api/documents/text", json={"text": "for workspace id"}).json()
        storage_key = f"{doc['workspace_id']}/too-big.pdf"
        response = client.post(
            "/api/documents/pdf", json={"storage_key": storage_key, "title": "Too big"}
        )

    assert response.status_code == 422


def test_create_pdf_document_succeeds_and_enqueues_ingestion(ingestion_app, monkeypatch) -> None:
    enqueued: list[str] = []
    monkeypatch.setattr(
        documents_routes.worker_ingestion_tasks.ingest_pdf_document, "delay",
        lambda document_id: enqueued.append(document_id),
    )

    monkeypatch.setattr(documents_routes.storage, "stat_object", lambda key: {"size": 1024})

    with TestClient(ingestion_app[0]) as client:
        doc = client.post("/api/documents/text", json={"text": "for workspace id"}).json()
        storage_key = f"{doc['workspace_id']}/upload.pdf"
        response = client.post(
            "/api/documents/pdf", json={"storage_key": storage_key, "title": "My PDF"}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["source_type"] == "pdf"
    assert body["ingestion_status"] == "pending"
    assert body["segment_count"] == 0
    assert enqueued == [body["id"]]


def test_create_url_document_rejects_internal_address(ingestion_app) -> None:
    app, _ = ingestion_app
    with TestClient(app) as client:
        response = client.post("/api/documents/url", json={"url": "http://127.0.0.1/secret"})

    assert response.status_code == 422


def test_create_url_document_creates_pending_and_dedupes(ingestion_app, monkeypatch) -> None:
    monkeypatch.setattr(documents_routes, "assert_public_url", lambda url: url)
    enqueued: list[str] = []
    monkeypatch.setattr(
        documents_routes.worker_ingestion_tasks.ingest_url_document, "delay",
        lambda document_id: enqueued.append(document_id),
    )

    app, _ = ingestion_app
    with TestClient(app) as client:
        first = client.post("/api/documents/url", json={"url": "http://example.com/article"})
        second = client.post("/api/documents/url", json={"url": "http://example.com/article"})

    assert first.status_code == 201
    assert first.json()["ingestion_status"] == "pending"
    assert first.json()["source_type"] == "url"
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    # Only the first (creating) request enqueues an ingestion task.
    assert enqueued == [first.json()["id"]]


def test_get_document_ingestion_reports_status_and_segment_count(ingestion_app, monkeypatch) -> None:
    monkeypatch.setattr(documents_routes, "assert_public_url", lambda url: url)

    app, runtime = ingestion_app

    async def mark_ready(document_id: str):
        from documents import service
        from documents.models import Document
        async with runtime.sessions() as db:
            document = await db.get(Document, uuid.UUID(document_id))
            await service.replace_segments_for_document(db, document=document, segments=[])
            await service.mark_ingestion_ready(
                db, document=document, raw_text="hello", normalized_text="hello",
            )

    with TestClient(app) as client:
        created = client.post("/api/documents/url", json={"url": "http://example.com/page"}).json()
        asyncio.run(mark_ready(created["id"]))
        response = client.get(f"/api/documents/{created['id']}/ingestion")

    assert response.status_code == 200
    body = response.json()
    assert body["ingestion_status"] == "ready"
    assert body["segment_count"] == 0


def test_extraction_job_blocked_until_document_ready(ingestion_app, monkeypatch) -> None:
    monkeypatch.setattr(documents_routes, "assert_public_url", lambda url: url)

    app, _ = ingestion_app
    with TestClient(app) as client:
        document = client.post("/api/documents/url", json={"url": "http://example.com/pending"}).json()
        assert document["ingestion_status"] == "pending"

        response = client.post(
            "/api/extraction-jobs",
            json={
                "document_id": document["id"],
                "model": "test-model",
                "prompt_type": "temel",
                "kg_type": "wikipedia",
                "embedding_model": "contriever",
                "ontology_language": "en",
            },
        )

    assert response.status_code == 409
