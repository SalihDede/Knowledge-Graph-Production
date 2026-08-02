from __future__ import annotations

import asyncio
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
import documents.models  # noqa: F401  (register tables on Base.metadata)
from documents.routes import router as documents_router


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
def documents_app(tmp_path: Path):
    database_path = tmp_path / "documents.sqlite3"
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
    yield app, runtime
    asyncio.run(engine.dispose())


def test_create_document_normalizes_and_hashes(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            json={"text": "  Merhaba   dünya.\r\n\r\n\r\nİkinci paragraf.  \n", "title": "Test"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["normalized_text"] == "Merhaba   dünya.\n\nİkinci paragraf."
    assert len(body["content_hash"]) == 64
    assert body["char_count"] == len(body["normalized_text"])


def test_duplicate_document_is_reused(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        first = client.post("/api/documents", json={"text": "Aynı metin."})
        second = client.post("/api/documents", json={"text": "Aynı metin."})
        listing = client.get("/api/documents")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(listing.json()) == 1


def test_get_document_requires_ownership(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client_a, TestClient(app) as client_b:
        created = client_a.post("/api/documents", json={"text": "Sahiplik testi."})
        document_id = created.json()["id"]

        own_fetch = client_a.get(f"/api/documents/{document_id}")
        other_fetch = client_b.get(f"/api/documents/{document_id}")

    assert own_fetch.status_code == 200
    assert other_fetch.status_code == 404


def test_extraction_job_dedup_and_reuse(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Job için metin."}).json()
        job_payload = {
            "document_id": document["id"],
            "model": "test-model",
            "prompt_type": "temel",
            "kg_type": "wikipedia",
            "embedding_model": "contriever",
            "ontology_language": "en",
        }

        first_job = client.post("/api/extraction-jobs", json=job_payload)
        second_job = client.post("/api/extraction-jobs", json=job_payload)
        fetched = client.get(f"/api/extraction-jobs/{first_job.json()['id']}")

    assert first_job.status_code == 201
    assert first_job.json()["status"] == "queued"
    assert second_job.status_code == 200
    assert second_job.json()["id"] == first_job.json()["id"]
    assert fetched.status_code == 200
    assert fetched.json()["id"] == first_job.json()["id"]


def test_extraction_job_different_pipeline_creates_new_job(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Farklı pipeline."}).json()
        base_payload = {
            "document_id": document["id"],
            "model": "test-model",
            "prompt_type": "temel",
            "kg_type": "wikipedia",
            "embedding_model": "contriever",
            "ontology_language": "en",
        }
        other_payload = {**base_payload, "prompt_type": "ape"}

        first_job = client.post("/api/extraction-jobs", json=base_payload)
        second_job = client.post("/api/extraction-jobs", json=other_payload)

    assert first_job.json()["id"] != second_job.json()["id"]
    assert first_job.json()["pipeline_fingerprint"] != second_job.json()["pipeline_fingerprint"]


def test_extraction_job_for_missing_document_returns_404(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        response = client.post(
            "/api/extraction-jobs",
            json={
                "document_id": "00000000-0000-0000-0000-000000000000",
                "model": "test-model",
            },
        )

    assert response.status_code == 404


def test_login_migrates_anonymous_workspace_to_user(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        created = client.post("/api/documents", json={"text": "Anonim doküman."})
        document_id = created.json()["id"]

        client.post(
            "/api/auth/register",
            json={
                "email": "owner@example.com",
                "password": "correct-horse-battery-staple",
                "display_name": "Owner",
            },
        )

        after_login = client.get(f"/api/documents/{document_id}")

    assert after_login.status_code == 200
