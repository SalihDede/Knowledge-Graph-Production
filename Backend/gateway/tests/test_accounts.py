from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from accounts.config import AuthSettings
from accounts.middleware import IdentityMiddleware
from accounts.models import AnonymousVisitor, Base, User
from accounts.routes import router
from accounts.runtime import AuthRuntime
from fakes import MemorySessionStore


@pytest.fixture()
def account_app(tmp_path: Path):
    database_path = tmp_path / "accounts.sqlite3"
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
    app.include_router(router)
    yield app, runtime
    asyncio.run(engine.dispose())


def test_anonymous_identity_is_stable(account_app) -> None:
    app, _ = account_app
    with TestClient(app) as client:
        first = client.get("/api/auth/me")
        second = client.get("/api/auth/me")

    assert first.status_code == 200
    assert first.json()["authenticated"] is False
    assert first.json()["visitor_id"] == second.json()["visitor_id"]
    assert "kg_visitor=" in first.headers["set-cookie"]


def test_register_claims_visitor_and_creates_session(account_app) -> None:
    app, runtime = account_app
    with TestClient(app) as client:
        anonymous = client.get("/api/auth/me").json()
        response = client.post(
            "/api/auth/register",
            json={
                "email": "User@Example.COM",
                "password": "correct-horse-battery-staple",
                "display_name": "Test User",
            },
        )
        current = client.get("/api/auth/me")

    assert response.status_code == 201
    assert response.json()["authenticated"] is True
    assert response.json()["user"]["email"] == "user@example.com"
    assert current.json()["user"]["display_name"] == "Test User"
    assert "kg_session=" in response.headers["set-cookie"]

    async def load_records():
        async with runtime.sessions() as db:
            user = await db.scalar(select(User).where(User.email == "user@example.com"))
            visitor = await db.get(AnonymousVisitor, uuid.UUID(anonymous["visitor_id"]))
            return user, visitor

    user, visitor = asyncio.run(load_records())
    assert user is not None
    assert user.password_hash != "correct-horse-battery-staple"
    assert visitor.claimed_by_user_id == user.id


def test_logout_and_login_round_trip(account_app) -> None:
    app, _ = account_app
    with TestClient(app) as client:
        client.get("/api/auth/me")
        client.post(
            "/api/auth/register",
            json={
                "email": "person@example.com",
                "password": "correct-horse-battery-staple",
                "display_name": "Person",
            },
        )
        logout = client.post("/api/auth/logout")
        anonymous = client.get("/api/auth/me")
        bad_login = client.post(
            "/api/auth/login",
            json={"email": "person@example.com", "password": "wrong"},
        )
        login = client.post(
            "/api/auth/login",
            json={
                "email": "person@example.com",
                "password": "correct-horse-battery-staple",
            },
        )

    assert logout.json()["authenticated"] is False
    assert anonymous.json()["authenticated"] is False
    assert bad_login.status_code == 401
    assert login.status_code == 200
    assert login.json()["authenticated"] is True


def test_duplicate_registration_is_rejected(account_app) -> None:
    app, _ = account_app
    payload = {
        "email": "duplicate@example.com",
        "password": "correct-horse-battery-staple",
        "display_name": "Duplicate",
    }
    with TestClient(app) as client:
        client.get("/api/auth/me")
        assert client.post("/api/auth/register", json=payload).status_code == 201
        duplicate = client.post("/api/auth/register", json=payload)

    assert duplicate.status_code == 409


def test_tampered_visitor_cookie_is_replaced(account_app) -> None:
    app, _ = account_app
    with TestClient(app) as client:
        client.cookies.set("kg_visitor", "tampered")
        response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["visitor_id"]
    assert "kg_visitor=" in response.headers["set-cookie"]
