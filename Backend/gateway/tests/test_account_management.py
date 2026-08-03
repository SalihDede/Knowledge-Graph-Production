from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import accounts.routes as accounts_routes
from accounts.config import AuthSettings
from accounts.middleware import IdentityMiddleware
from accounts.models import AuthToken, AuthTokenPurpose, Base, User, utc_now
from accounts.routes import router as auth_router
from accounts.runtime import AuthRuntime
import documents.models  # noqa: F401  (register tables on the shared Base.metadata)
from documents.models import Document, DocumentSourceType, IngestionStatus, Workspace
from fakes import MemorySessionStore

REGISTER_PAYLOAD = {
    "email": "person@example.com",
    "password": "correct-horse-battery-staple",
    "display_name": "Person",
}


def _build_app(tmp_path: Path):
    database_path = tmp_path / "accounts.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    # SQLite ignores ON DELETE CASCADE unless foreign key enforcement is
    # turned on per-connection -- without this, the account-deletion
    # cascade test below would pass for the wrong reason (assertions
    # against rows that were never really cascade-deleted).
    event.listens_for(engine.sync_engine, "connect")(
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON")
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
        email_verification_ttl_seconds=86400,
        password_reset_ttl_seconds=3600,
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
    return app, runtime


@pytest.fixture()
def app_and_runtime(tmp_path: Path):
    app, runtime = _build_app(tmp_path)
    yield app, runtime
    asyncio.run(runtime.engine.dispose())


@pytest.fixture()
def captured_tokens(monkeypatch):
    """Captures tokens the placeholder "email" delivery would have sent,
    since only their hash is ever persisted (see accounts/routes.py)."""
    calls: list[dict] = []
    monkeypatch.setattr(
        accounts_routes, "_deliver_email_placeholder",
        lambda **kwargs: calls.append(kwargs),
    )
    return calls


def _register(client: TestClient, payload: dict = REGISTER_PAYLOAD) -> dict:
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201
    return response.json()


# ── Email verification ──────────────────────────────────────────────────────

def test_email_verification_request_requires_login(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        response = client.post("/api/auth/email/verification/request")

    assert response.status_code == 401


def test_email_verification_round_trip(app_and_runtime, captured_tokens) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        request_response = client.post("/api/auth/email/verification/request")
        assert request_response.status_code == 200
        assert len(captured_tokens) == 1
        token = captured_tokens[0]["token"]

        confirm_response = client.post(
            "/api/auth/email/verification/confirm", json={"token": token}
        )
        me = client.get("/api/auth/me")

    assert confirm_response.status_code == 200
    assert me.json()["user"]["email_verified"] is True


def test_email_verification_request_is_noop_once_verified(app_and_runtime, captured_tokens) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        client.post("/api/auth/email/verification/request")
        token = captured_tokens[0]["token"]
        client.post("/api/auth/email/verification/confirm", json={"token": token})

        second_request = client.post("/api/auth/email/verification/request")

    assert second_request.status_code == 200
    assert len(captured_tokens) == 1  # no second token issued


def test_email_verification_confirm_rejects_unknown_token(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/email/verification/confirm", json={"token": "not-a-real-token"}
        )

    assert response.status_code == 400


def test_email_verification_confirm_rejects_expired_token(app_and_runtime, captured_tokens) -> None:
    app, runtime = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        client.post("/api/auth/email/verification/request")
        token = captured_tokens[0]["token"]

    async def expire_token():
        async with runtime.sessions() as db:
            record = await db.scalar(
                select(AuthToken).where(AuthToken.purpose == AuthTokenPurpose.email_verification)
            )
            record.expires_at = utc_now() - timedelta(seconds=1)
            await db.commit()

    asyncio.run(expire_token())

    with TestClient(app) as client:
        response = client.post("/api/auth/email/verification/confirm", json={"token": token})

    assert response.status_code == 400


# ── Password reset ───────────────────────────────────────────────────────────

def test_password_reset_request_is_silent_for_unknown_email(app_and_runtime, captured_tokens) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/password/reset/request", json={"email": "nobody@example.com"}
        )

    assert response.status_code == 200
    assert captured_tokens == []


def test_password_reset_round_trip_and_old_password_stops_working(app_and_runtime, captured_tokens) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        client.post("/api/auth/logout")

        request_response = client.post(
            "/api/auth/password/reset/request", json={"email": REGISTER_PAYLOAD["email"]}
        )
        assert request_response.status_code == 200
        token = captured_tokens[0]["token"]

        confirm_response = client.post(
            "/api/auth/password/reset/confirm",
            json={"token": token, "new_password": "a-brand-new-password"},
        )

        old_login = client.post(
            "/api/auth/login",
            json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
        )
        new_login = client.post(
            "/api/auth/login",
            json={"email": REGISTER_PAYLOAD["email"], "password": "a-brand-new-password"},
        )

    assert confirm_response.status_code == 200
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_password_reset_confirm_rejects_unknown_token(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/password/reset/confirm",
            json={"token": "not-a-real-token", "new_password": "a-brand-new-password"},
        )

    assert response.status_code == 400


def test_password_reset_invalidates_existing_sessions(app_and_runtime, captured_tokens) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        before_reset = client.get("/api/auth/me").json()
        assert before_reset["authenticated"] is True

        client.post("/api/auth/password/reset/request", json={"email": REGISTER_PAYLOAD["email"]})
        token = captured_tokens[0]["token"]
        client.post(
            "/api/auth/password/reset/confirm",
            json={"token": token, "new_password": "a-brand-new-password"},
        )

        # Same cookie jar, but the session behind it should now be dead.
        after_reset = client.get("/api/auth/me")

    assert after_reset.json()["authenticated"] is False


# ── Active sessions ──────────────────────────────────────────────────────────

def test_list_sessions_requires_login(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        response = client.get("/api/auth/sessions")

    assert response.status_code == 401


def test_list_sessions_shows_current_session(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        response = client.get("/api/auth/sessions")

    body = response.json()
    assert len(body) == 1
    assert body[0]["is_current"] is True


def test_revoke_specific_session_logs_out_that_device(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client_a, TestClient(app) as client_b:
        _register(client_a)
        client_b.post(
            "/api/auth/login",
            json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
        )

        sessions = client_a.get("/api/auth/sessions").json()
        assert len(sessions) == 2
        other_session_id = next(s["id"] for s in sessions if not s["is_current"])

        revoke_response = client_a.delete(f"/api/auth/sessions/{other_session_id}")
        b_after = client_b.get("/api/auth/me")
        a_after = client_a.get("/api/auth/me")

    assert revoke_response.status_code == 204
    assert b_after.json()["authenticated"] is False
    assert a_after.json()["authenticated"] is True


def test_revoke_unknown_session_returns_404(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        response = client.delete("/api/auth/sessions/not-a-real-session-id")

    assert response.status_code == 404


def test_revoke_all_sessions_keeps_current_by_default(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client_a, TestClient(app) as client_b:
        _register(client_a)
        client_b.post(
            "/api/auth/login",
            json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
        )

        revoke_response = client_a.delete("/api/auth/sessions")
        a_after = client_a.get("/api/auth/me")
        b_after = client_b.get("/api/auth/me")

    assert revoke_response.status_code == 200
    assert a_after.json()["authenticated"] is True
    assert b_after.json()["authenticated"] is False


def test_revoke_all_sessions_including_current_logs_out_everywhere(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        revoke_response = client.delete("/api/auth/sessions", params={"include_current": "true"})
        after = client.get("/api/auth/me")

    assert revoke_response.status_code == 200
    assert after.json()["authenticated"] is False


# ── Account deletion ─────────────────────────────────────────────────────────

def test_delete_account_requires_login(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        response = client.request(
            "DELETE", "/api/auth/account", json={"password": "irrelevant"}
        )

    assert response.status_code == 401


def test_delete_account_rejects_wrong_password(app_and_runtime) -> None:
    app, _ = app_and_runtime
    with TestClient(app) as client:
        _register(client)
        response = client.request("DELETE", "/api/auth/account", json={"password": "wrong-password"})

    assert response.status_code == 401


def test_delete_account_removes_user_cascades_and_cleans_storage(app_and_runtime, monkeypatch) -> None:
    app, runtime = app_and_runtime
    deleted_keys: list[str] = []
    monkeypatch.setattr(accounts_routes.storage, "delete_object", lambda key: deleted_keys.append(key))

    with TestClient(app) as client:
        identity = _register(client)
        user_id = uuid.UUID(identity["user"]["id"])

        async def seed_pdf_document():
            async with runtime.sessions() as db:
                workspace = Workspace(owner_user_id=user_id)
                db.add(workspace)
                await db.flush()
                document = Document(
                    workspace_id=workspace.id,
                    created_by_user_id=user_id,
                    source_type=DocumentSourceType.pdf,
                    ingestion_status=IngestionStatus.ready,
                    storage_key=f"{workspace.id}/uploaded.pdf",
                )
                db.add(document)
                await db.commit()
                return workspace.id

        workspace_id = asyncio.run(seed_pdf_document())

        response = client.request(
            "DELETE", "/api/auth/account", json={"password": REGISTER_PAYLOAD["password"]}
        )
        after = client.get("/api/auth/me")

    assert response.status_code == 200
    assert after.json()["authenticated"] is False
    assert deleted_keys == [f"{workspace_id}/uploaded.pdf"]

    async def load_remaining():
        async with runtime.sessions() as db:
            user = await db.get(User, user_id)
            workspace = await db.get(Workspace, workspace_id)
            return user, workspace

    user, workspace = asyncio.run(load_remaining())
    assert user is None
    assert workspace is None  # cascaded away with the user
