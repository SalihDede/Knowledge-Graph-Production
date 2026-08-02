from __future__ import annotations

import json
from dataclasses import dataclass

from redis.asyncio import Redis

from .security import create_session_token, token_digest


@dataclass(frozen=True)
class SessionData:
    user_id: str
    visitor_id: str


class RedisSessionStore:
    def __init__(self, redis: Redis, ttl_seconds: int):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(token: str) -> str:
        return f"auth:session:{token_digest(token)}"

    async def create(self, data: SessionData) -> str:
        token = create_session_token()
        await self.redis.set(
            self._key(token),
            json.dumps({"user_id": data.user_id, "visitor_id": data.visitor_id}),
            ex=self.ttl_seconds,
        )
        return token

    async def get(self, token: str) -> SessionData | None:
        raw = await self.redis.get(self._key(token))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        await self.redis.expire(self._key(token), self.ttl_seconds)
        return SessionData(
            user_id=str(payload["user_id"]),
            visitor_id=str(payload["visitor_id"]),
        )

    async def delete(self, token: str) -> None:
        await self.redis.delete(self._key(token))

    async def ping(self) -> bool:
        return bool(await self.redis.ping())
