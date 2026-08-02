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
from accounts.security import create_session_token
from accounts.store import SessionData
from documents.models import Document, ExtractionJob
from documents.routes import router as documents_router
import documents.routes as documents_routes
import triples.models  # noqa: F401  (register tables on Base.metadata)
from triples.routes import router as triples_router
from triples.service import TripleEvidenceInput, TripleInput, record_triples_for_job


class MemorySessionStore:
    def __init__(self):
        self.sessions: dict[str, SessionData] = {}

    async def create(self, data: SessionData) -> str:
        token = create_session_token()
        self.sessions[token] = data
        return token

    async def get(self, token: str) -> SessionData | None:
        return self.sessions.get(token)

    async def delete(self, token: str) -> None:
        self.sessions.pop(token, None)

    async def ping(self) -> bool:
        return True


@pytest.fixture()
def triples_app(tmp_path: Path, monkeypatch):
    # These tests exercise the HTTP layer, not the Celery dispatch; avoid a real
    # (and here, unreachable) broker call on every job-creation test.
    monkeypatch.setattr(documents_routes.run_extraction_job, "delay", lambda *a, **kw: None)
    # These tests use placeholder model ids; the OpenRouter allow-list is
    # covered separately in tests/test_policy.py.
    monkeypatch.setattr("catalog.registry.is_model_allowed", lambda *a, **kw: True)

    database_path = tmp_path / "triples.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
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
    app.include_router(triples_router)
    yield app, runtime
    asyncio.run(engine.dispose())


def _seed_job_with_triples(runtime, document_id: str, job_id: str) -> str:
    async def scenario() -> str:
        async with runtime.sessions() as db:
            document = await db.get(Document, uuid.UUID(document_id))
            job = await db.get(ExtractionJob, uuid.UUID(job_id))
            triples = await record_triples_for_job(
                db,
                job=job,
                document=document,
                triples=[
                    TripleInput(
                        subject="Atatürk",
                        subject_type="Kişi",
                        predicate="doğum_yeri",
                        object="Selanik",
                        object_type="Yer",
                        evidence=[
                            TripleEvidenceInput(
                                source_text="Atatürk 1881 yılında Selanik'te doğdu.",
                                char_start=0,
                                char_end=38,
                            )
                        ],
                    )
                ],
            )
            return str(triples[0].id)

    return asyncio.run(scenario())


def _create_document_and_job(client: TestClient) -> tuple[str, str]:
    document = client.post("/api/documents", json={"text": "Atatürk 1881 yılında Selanik'te doğdu."}).json()
    job = client.post(
        "/api/extraction-jobs",
        json={
            "document_id": document["id"],
            "model": "test-model",
        },
    ).json()
    return document["id"], job["id"]


def test_list_job_triples_returns_evidence(triples_app) -> None:
    app, runtime = triples_app
    with TestClient(app) as client:
        document_id, job_id = _create_document_and_job(client)
        triple_id = _seed_job_with_triples(runtime, document_id, job_id)

        response = client.get(f"/api/extraction-jobs/{job_id}/triples")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == triple_id
    assert body[0]["subject"] == "Atatürk"
    assert body[0]["object"] == "Selanik"
    assert body[0]["status"] == "candidate"
    assert len(body[0]["evidence"]) == 1
    assert body[0]["evidence"][0]["char_start"] == 0
    assert body[0]["evidence"][0]["char_end"] == 38


def test_get_triple_detail(triples_app) -> None:
    app, runtime = triples_app
    with TestClient(app) as client:
        document_id, job_id = _create_document_and_job(client)
        triple_id = _seed_job_with_triples(runtime, document_id, job_id)

        response = client.get(f"/api/triples/{triple_id}")

    assert response.status_code == 200
    assert response.json()["id"] == triple_id
    assert response.json()["predicate"] == "doğum_yeri"


def test_update_triple_status(triples_app) -> None:
    app, runtime = triples_app
    with TestClient(app) as client:
        document_id, job_id = _create_document_and_job(client)
        triple_id = _seed_job_with_triples(runtime, document_id, job_id)

        response = client.patch(f"/api/triples/{triple_id}/status", json={"status": "verified"})
        fetched = client.get(f"/api/triples/{triple_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert fetched.json()["status"] == "verified"


def test_triple_endpoints_reject_invalid_status(triples_app) -> None:
    app, runtime = triples_app
    with TestClient(app) as client:
        document_id, job_id = _create_document_and_job(client)
        triple_id = _seed_job_with_triples(runtime, document_id, job_id)

        response = client.patch(f"/api/triples/{triple_id}/status", json={"status": "unknown"})

    assert response.status_code == 422


def test_triple_access_is_isolated_per_identity(triples_app) -> None:
    app, runtime = triples_app
    with TestClient(app) as owner_client, TestClient(app) as other_client:
        document_id, job_id = _create_document_and_job(owner_client)
        triple_id = _seed_job_with_triples(runtime, document_id, job_id)

        other_client.get("/api/auth/me")
        other_triple = other_client.get(f"/api/triples/{triple_id}")
        other_job_triples = other_client.get(f"/api/extraction-jobs/{job_id}/triples")
        other_patch = other_client.patch(
            f"/api/triples/{triple_id}/status", json={"status": "rejected"}
        )

    assert other_triple.status_code == 404
    assert other_job_triples.status_code == 404
    assert other_patch.status_code == 404


def test_missing_triple_returns_404(triples_app) -> None:
    app, _ = triples_app
    with TestClient(app) as client:
        client.get("/api/auth/me")
        response = client.get(f"/api/triples/{uuid.uuid4()}")

    assert response.status_code == 404
