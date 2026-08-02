from __future__ import annotations

from fastapi import FastAPI
from itsdangerous import URLSafeTimedSerializer
from redis.asyncio import Redis
from sqlalchemy import text

from .config import AuthSettings
from .database import create_database
from .middleware import IdentityMiddleware
from .routes import router
from .runtime import AuthRuntime
from .store import RedisSessionStore


def install_accounts(app: FastAPI, settings: AuthSettings | None = None) -> AuthRuntime | None:
    settings = settings or AuthSettings.from_env()
    if not settings.enabled:
        return None

    if len(settings.cookie_secret) < 32:
        raise RuntimeError("AUTH_COOKIE_SECRET en az 32 karakter olmalıdır")

    engine, sessions = create_database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    runtime = AuthRuntime(
        settings=settings,
        engine=engine,
        sessions=sessions,
        session_store=RedisSessionStore(redis, settings.session_ttl_seconds),
        visitor_signer=URLSafeTimedSerializer(settings.cookie_secret),
    )
    app.state.accounts = runtime
    app.add_middleware(IdentityMiddleware, runtime=runtime)
    app.include_router(router)
    return runtime


async def accounts_ready(app: FastAPI) -> bool:
    runtime: AuthRuntime | None = getattr(app.state, "accounts", None)
    if runtime is None:
        return True
    async with runtime.sessions() as db:
        await db.execute(text("SELECT 1"))
    return await runtime.session_store.ping()
