from __future__ import annotations

from dataclasses import dataclass

from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .config import AuthSettings
from .store import RedisSessionStore


@dataclass
class AuthRuntime:
    settings: AuthSettings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    session_store: RedisSessionStore
    visitor_signer: URLSafeTimedSerializer
