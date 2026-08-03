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
def documents_app(tmp_path: Path, monkeypatch):
    # These tests exercise the HTTP layer, not the Celery dispatch; avoid a real
    # (and here, unreachable) broker call on every job-creation test.
    monkeypatch.setattr(documents_routes.worker_tasks.run_extraction_job, "delay", lambda *a, **kw: None)
    # These tests use placeholder model ids; the OpenRouter allow-list is
    # covered separately in tests/test_policy.py and below via strict_documents_app.
    monkeypatch.setattr("catalog.registry.is_model_allowed", lambda *a, **kw: True)

    app, runtime, engine = _build_documents_app(tmp_path)
    yield app, runtime
    asyncio.run(engine.dispose())


@pytest.fixture()
def strict_documents_app(tmp_path: Path, monkeypatch):
    # Same as documents_app but with the real OpenRouter allow-list enforced,
    # for testing extraction policy rejections end-to-end.
    monkeypatch.setattr(documents_routes.worker_tasks.run_extraction_job, "delay", lambda *a, **kw: None)

    app, runtime, engine = _build_documents_app(tmp_path)
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


def test_extraction_job_stores_full_pipeline_params(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Pipeline parametreleri."}).json()
        response = client.post(
            "/api/extraction-jobs",
            json={
                "document_id": document["id"],
                "model": "test-model",
                "prompt_type": "dspy",
                "kg_type": "kggen",
                "embedding_model": "bge_m3",
                "ontology_language": "tr",
            },
        )

    body = response.json()
    assert body["model"] == "test-model"
    assert body["prompt_type"] == "dspy"
    assert body["kg_type"] == "kggen"
    assert body["embedding_model"] == "bge_m3"
    assert body["ontology_language"] == "tr"
    assert body["pipeline_version"] == "v1"


def test_concurrent_extraction_job_requests_reuse_single_job(documents_app) -> None:
    from sqlalchemy import select

    from documents import service
    from documents.models import Document, ExtractionJob

    app, runtime = documents_app
    with TestClient(app) as client:
        document_payload = client.post("/api/documents", json={"text": "Yarış testi."}).json()
        visitor_id = uuid.UUID(client.get("/api/auth/me").json()["visitor_id"])

    async def scenario():
        async with runtime.sessions() as db_a, runtime.sessions() as db_b:
            document_a = await db_a.get(Document, uuid.UUID(document_payload["id"]))
            document_b = await db_b.get(Document, uuid.UUID(document_payload["id"]))
            return await asyncio.gather(
                service.create_or_reuse_extraction_job(
                    db_a,
                    document=document_a,
                    user=None,
                    visitor_id=visitor_id,
                    kg_type="wikipedia",
                    prompt_type="temel",
                    embedding_model="contriever",
                    ontology_language="en",
                    model="race-model",
                ),
                service.create_or_reuse_extraction_job(
                    db_b,
                    document=document_b,
                    user=None,
                    visitor_id=visitor_id,
                    kg_type="wikipedia",
                    prompt_type="temel",
                    embedding_model="contriever",
                    ontology_language="en",
                    model="race-model",
                ),
            )

    results = asyncio.run(scenario())
    job_ids = {str(job.id) for job, _created in results}
    assert len(job_ids) == 1

    async def count_jobs() -> list[ExtractionJob]:
        async with runtime.sessions() as db:
            rows = await db.scalars(select(ExtractionJob))
            return list(rows)

    jobs = asyncio.run(count_jobs())
    assert len(jobs) == 1


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


def test_create_document_rejects_text_over_max_length(documents_app) -> None:
    import policy

    app, _ = documents_app
    with TestClient(app) as client:
        response = client.post(
            "/api/documents",
            json={"text": "a" * (policy.MAX_EXTRACTION_CHARS + 1)},
        )

    assert response.status_code == 422


ALLOWED_MODEL = "google/gemini-2.5-flash-lite"
ANOTHER_ALLOWED_MODEL = "openai/gpt-4o-mini"


@pytest.mark.parametrize(
    "field,value",
    [
        ("kg_type", "not-a-real-kg-type"),
        ("prompt_type", "not-a-real-prompt-type"),
        ("embedding_model", "not-a-real-embedding-model"),
        ("ontology_language", "fr"),
    ],
)
def test_create_extraction_job_rejects_invalid_pipeline_field(
    strict_documents_app, field: str, value: str
) -> None:
    app, _ = strict_documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Policy testi."}).json()
        payload = {
            "document_id": document["id"],
            "model": ALLOWED_MODEL,
            "prompt_type": "temel",
            "kg_type": "wikipedia",
            "embedding_model": "contriever",
            "ontology_language": "en",
        }
        payload[field] = value

        response = client.post("/api/extraction-jobs", json=payload)

    assert response.status_code == 422


def test_create_extraction_job_rejects_model_outside_full_catalog(strict_documents_app) -> None:
    app, _ = strict_documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Model testi."}).json()

        response = client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": "not-a-real-model"},
        )

    assert response.status_code == 422


def test_create_extraction_job_rejects_model_outside_anonymous_allowlist(
    strict_documents_app, monkeypatch
) -> None:
    monkeypatch.delenv("ANONYMOUS_MODEL_ALLOWLIST", raising=False)
    app, _ = strict_documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Anonim model testi."}).json()

        response = client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": ANOTHER_ALLOWED_MODEL},
        )

    assert response.status_code == 422


def test_create_extraction_job_allows_default_anonymous_model(
    strict_documents_app, monkeypatch
) -> None:
    monkeypatch.delenv("ANONYMOUS_MODEL_ALLOWLIST", raising=False)
    app, _ = strict_documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Anonim model testi 2."}).json()

        response = client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": ALLOWED_MODEL},
        )

    assert response.status_code == 201


def test_create_extraction_job_enforces_active_job_limit_per_workspace(
    strict_documents_app,
) -> None:
    import policy

    app, _ = strict_documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Kota testi."}).json()

        responses = []
        for index in range(policy.MAX_ACTIVE_JOBS_PER_WORKSPACE + 1):
            responses.append(
                client.post(
                    "/api/extraction-jobs",
                    json={
                        "document_id": document["id"],
                        "model": ALLOWED_MODEL,
                        # Distinct prompt_type per request avoids job dedup so
                        # each call actually tries to open a *new* job.
                        "prompt_type": ["temel", "ape", "dspy", "textgrad"][index],
                    },
                )
            )

    statuses = [response.status_code for response in responses]
    assert statuses[: policy.MAX_ACTIVE_JOBS_PER_WORKSPACE] == [201] * policy.MAX_ACTIVE_JOBS_PER_WORKSPACE
    assert statuses[-1] == 429


def test_list_extraction_jobs_orders_newest_first(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Sıralama testi."}).json()
        first = client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": "test-model", "prompt_type": "temel"},
        ).json()
        second = client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": "test-model", "prompt_type": "ape"},
        ).json()

        listing = client.get("/api/extraction-jobs").json()

    assert [job["id"] for job in listing] == [second["id"], first["id"]]


def test_list_extraction_jobs_paginates(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Sayfalama testi."}).json()
        job_ids = []
        for prompt_type in ["temel", "ape", "dspy"]:
            job = client.post(
                "/api/extraction-jobs",
                json={"document_id": document["id"], "model": "test-model", "prompt_type": prompt_type},
            ).json()
            job_ids.append(job["id"])

        first_page = client.get("/api/extraction-jobs", params={"limit": 2, "offset": 0}).json()
        second_page = client.get("/api/extraction-jobs", params={"limit": 2, "offset": 2}).json()

    assert [job["id"] for job in first_page] == list(reversed(job_ids))[:2]
    assert [job["id"] for job in second_page] == list(reversed(job_ids))[2:]


def test_list_extraction_jobs_filters_by_status(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document = client.post("/api/documents", json={"text": "Durum filtresi testi."}).json()
        client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": "test-model"},
        )

        queued_only = client.get("/api/extraction-jobs", params={"status": "queued"}).json()
        completed_only = client.get("/api/extraction-jobs", params={"status": "completed"}).json()

    assert len(queued_only) == 1
    assert queued_only[0]["status"] == "queued"
    assert completed_only == []


def test_list_extraction_jobs_filters_by_document_id(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        document_a = client.post("/api/documents", json={"text": "Doküman A."}).json()
        document_b = client.post("/api/documents", json={"text": "Doküman B."}).json()
        job_a = client.post(
            "/api/extraction-jobs",
            json={"document_id": document_a["id"], "model": "test-model"},
        ).json()
        client.post(
            "/api/extraction-jobs",
            json={"document_id": document_b["id"], "model": "test-model"},
        )

        filtered = client.get(
            "/api/extraction-jobs", params={"document_id": document_a["id"]}
        ).json()

    assert [job["id"] for job in filtered] == [job_a["id"]]


def test_list_extraction_jobs_rejects_invalid_status_filter(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client:
        response = client.get("/api/extraction-jobs", params={"status": "not-a-real-status"})

    assert response.status_code == 422


def test_list_extraction_jobs_includes_summary_fields_without_raw_content(documents_app) -> None:
    import asyncio

    from documents.models import Document, ExtractionJob
    from triples.service import TripleInput, record_triples_for_job

    app, runtime = documents_app
    with TestClient(app) as client:
        document = client.post(
            "/api/documents",
            json={"text": "a" * 500, "title": "Uzun Başlık"},
        ).json()
        job = client.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": "test-model"},
        ).json()

        async def seed_triple():
            async with runtime.sessions() as db:
                job_row = await db.get(ExtractionJob, uuid.UUID(job["id"]))
                document_row = await db.get(Document, uuid.UUID(document["id"]))
                await record_triples_for_job(
                    db,
                    job=job_row,
                    document=document_row,
                    triples=[TripleInput(subject="A", predicate="rel", object="B")],
                )

        asyncio.run(seed_triple())

        response = client.get("/api/extraction-jobs")

    body = response.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["document_title"] == "Uzun Başlık"
    assert entry["triple_count"] == 1
    assert len(entry["document_preview"]) <= 201  # 200 chars + ellipsis
    assert "raw_text" not in entry
    assert "normalized_text" not in entry


def test_list_extraction_jobs_is_isolated_per_workspace(documents_app) -> None:
    app, _ = documents_app
    with TestClient(app) as client_a, TestClient(app) as client_b:
        document = client_a.post("/api/documents", json={"text": "İzolasyon testi."}).json()
        client_a.post(
            "/api/extraction-jobs",
            json={"document_id": document["id"], "model": "test-model"},
        )

        own_listing = client_a.get("/api/extraction-jobs").json()
        other_listing = client_b.get("/api/extraction-jobs").json()

    assert len(own_listing) == 1
    assert other_listing == []
