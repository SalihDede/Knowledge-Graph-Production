from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.models import AnonymousVisitor, Base, User, utc_now
import documents.models  # noqa: F401  (register tables on the shared Base.metadata)
from documents.models import Document, DocumentSourceType, IngestionStatus, Workspace
import storage
import worker.maintenance as maintenance


@pytest.fixture()
def sessions_factory(tmp_path: Path):
    database_path = tmp_path / "maintenance.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    # SQLite ignores ON DELETE CASCADE unless foreign key enforcement is
    # turned on per-connection -- needed for the visitor-cascade test below.
    event.listens_for(engine.sync_engine, "connect")(
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare())
    yield sessions
    asyncio.run(engine.dispose())


def _add_visitor(sessions, *, last_seen_at, claimed_by_user_id=None) -> uuid.UUID:
    async def run():
        async with sessions() as db:
            visitor = AnonymousVisitor(last_seen_at=last_seen_at, claimed_by_user_id=claimed_by_user_id)
            db.add(visitor)
            await db.commit()
            return visitor.id
    return asyncio.run(run())


# ── Anonymous visitor cleanup ────────────────────────────────────────────────

def test_removes_stale_unclaimed_visitor(sessions_factory, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "VISITOR_CLEANUP_STALE_SECONDS", 3600)
    visitor_id = _add_visitor(sessions_factory, last_seen_at=utc_now() - timedelta(hours=2))

    removed = asyncio.run(maintenance.sweep_stale_anonymous_visitors(sessions_factory))

    async def load():
        async with sessions_factory() as db:
            return await db.get(AnonymousVisitor, visitor_id)

    assert removed == 1
    assert asyncio.run(load()) is None


def test_keeps_recent_unclaimed_visitor(sessions_factory, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "VISITOR_CLEANUP_STALE_SECONDS", 3600)
    visitor_id = _add_visitor(sessions_factory, last_seen_at=utc_now())

    removed = asyncio.run(maintenance.sweep_stale_anonymous_visitors(sessions_factory))

    async def load():
        async with sessions_factory() as db:
            return await db.get(AnonymousVisitor, visitor_id)

    assert removed == 0
    assert asyncio.run(load()) is not None


def test_keeps_claimed_visitor_regardless_of_age(sessions_factory, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "VISITOR_CLEANUP_STALE_SECONDS", 3600)

    async def seed_user() -> uuid.UUID:
        async with sessions_factory() as db:
            user = User(email="claimed@example.com", display_name="Claimed", password_hash="x")
            db.add(user)
            await db.commit()
            return user.id

    user_id = asyncio.run(seed_user())
    visitor_id = _add_visitor(
        sessions_factory, last_seen_at=utc_now() - timedelta(days=365), claimed_by_user_id=user_id,
    )

    removed = asyncio.run(maintenance.sweep_stale_anonymous_visitors(sessions_factory))

    async def load():
        async with sessions_factory() as db:
            return await db.get(AnonymousVisitor, visitor_id)

    assert removed == 0
    assert asyncio.run(load()) is not None


def test_removing_stale_visitor_cascades_to_owned_workspace(sessions_factory, monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "VISITOR_CLEANUP_STALE_SECONDS", 3600)
    visitor_id = _add_visitor(sessions_factory, last_seen_at=utc_now() - timedelta(hours=2))

    async def seed_workspace():
        async with sessions_factory() as db:
            workspace = Workspace(owner_visitor_id=visitor_id)
            db.add(workspace)
            await db.commit()
            return workspace.id

    workspace_id = asyncio.run(seed_workspace())

    asyncio.run(maintenance.sweep_stale_anonymous_visitors(sessions_factory))

    async def load():
        async with sessions_factory() as db:
            return await db.get(Workspace, workspace_id)

    assert asyncio.run(load()) is None


# ── Orphaned storage cleanup ─────────────────────────────────────────────────

def test_deletes_object_with_no_matching_document(sessions_factory, monkeypatch) -> None:
    old = utc_now() - timedelta(days=2)
    monkeypatch.setattr(storage, "iter_objects", lambda: iter([("ws/orphan.pdf", old)]))
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))

    removed = asyncio.run(maintenance.sweep_orphaned_storage_objects(sessions_factory))

    assert removed == 1
    assert deleted == ["ws/orphan.pdf"]


def test_keeps_object_within_grace_period(sessions_factory, monkeypatch) -> None:
    recent = utc_now() - timedelta(minutes=5)
    monkeypatch.setattr(storage, "iter_objects", lambda: iter([("ws/fresh.pdf", recent)]))
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))

    removed = asyncio.run(maintenance.sweep_orphaned_storage_objects(sessions_factory))

    assert removed == 0
    assert deleted == []


def test_keeps_object_with_matching_document_even_if_failed(sessions_factory, monkeypatch) -> None:
    old = utc_now() - timedelta(days=2)
    storage_key = "ws/still-referenced.pdf"
    monkeypatch.setattr(storage, "iter_objects", lambda: iter([(storage_key, old)]))
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))

    async def seed_document():
        async with sessions_factory() as db:
            visitor = AnonymousVisitor()
            db.add(visitor)
            await db.flush()
            workspace = Workspace(owner_visitor_id=visitor.id)
            db.add(workspace)
            await db.flush()
            document = Document(
                workspace_id=workspace.id,
                source_type=DocumentSourceType.pdf,
                ingestion_status=IngestionStatus.failed,
                storage_key=storage_key,
            )
            db.add(document)
            await db.commit()

    asyncio.run(seed_document())

    removed = asyncio.run(maintenance.sweep_orphaned_storage_objects(sessions_factory))

    assert removed == 0
    assert deleted == []


# ── Wikontic health check ────────────────────────────────────────────────────

def _patch_httpx_client(monkeypatch, transport: httpx.MockTransport) -> None:
    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(maintenance.httpx, "AsyncClient", _PatchedAsyncClient)


@pytest.mark.asyncio
async def test_health_check_reports_ok_when_both_endpoints_healthy(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"status": "ok", "profiles": {"en__contriever": {"ok": True}}})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    result = await maintenance.check_wikontic_health()

    assert result["ready"]["ok"] is True
    assert result["profiles"]["ok"] is True


@pytest.mark.asyncio
async def test_health_check_reports_degraded_when_ready_endpoint_fails(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(503)
        return httpx.Response(200, json={"status": "ok", "profiles": {}})

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    result = await maintenance.check_wikontic_health()

    assert result["ready"]["ok"] is False


@pytest.mark.asyncio
async def test_health_check_reports_degraded_when_a_profile_is_unhealthy(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200, json={"status": "degraded", "profiles": {"en__contriever": {"ok": False}}}
        )

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    result = await maintenance.check_wikontic_health()

    assert result["profiles"]["ok"] is False


@pytest.mark.asyncio
async def test_health_check_handles_network_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_httpx_client(monkeypatch, httpx.MockTransport(handler))

    result = await maintenance.check_wikontic_health()

    assert result["ready"]["ok"] is False
    assert result["profiles"]["ok"] is False
