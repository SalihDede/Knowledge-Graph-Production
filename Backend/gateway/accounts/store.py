from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from redis.asyncio import Redis

from .security import create_session_token, token_digest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SessionData:
    user_id: str
    visitor_id: str


@dataclass(frozen=True)
class SessionSummary:
    """Public view of an active session for the "active sessions" UI. The
    id is a token digest, never the bearer token itself -- knowing it does
    not grant session hijack, unlike the raw session cookie value."""

    session_id: str
    created_at: str
    last_seen_at: str


class RedisSessionStore:
    def __init__(self, redis: Redis, ttl_seconds: int):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(token: str) -> str:
        return f"auth:session:{token_digest(token)}"

    @staticmethod
    def _session_key_from_digest(digest: str) -> str:
        return f"auth:session:{digest}"

    @staticmethod
    def _user_index_key(user_id: str) -> str:
        return f"auth:user_sessions:{user_id}"

    async def create(self, data: SessionData) -> str:
        token = create_session_token()
        now = _now_iso()
        await self.redis.set(
            self._key(token),
            json.dumps({
                "user_id": data.user_id,
                "visitor_id": data.visitor_id,
                "created_at": now,
                "last_seen_at": now,
            }),
            ex=self.ttl_seconds,
        )
        index_key = self._user_index_key(data.user_id)
        await self.redis.sadd(index_key, token_digest(token))
        await self.redis.expire(index_key, self.ttl_seconds)
        return token

    async def get(self, token: str) -> SessionData | None:
        key = self._key(token)
        raw = await self.redis.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(raw)
        payload["last_seen_at"] = _now_iso()
        await self.redis.set(key, json.dumps(payload), ex=self.ttl_seconds)
        await self.redis.expire(self._user_index_key(payload["user_id"]), self.ttl_seconds)
        return SessionData(
            user_id=str(payload["user_id"]),
            visitor_id=str(payload["visitor_id"]),
        )

    async def delete(self, token: str) -> None:
        digest = token_digest(token)
        raw = await self.redis.get(self._session_key_from_digest(digest))
        await self.redis.delete(self._session_key_from_digest(digest))
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            await self.redis.srem(self._user_index_key(payload["user_id"]), digest)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def list_for_user(self, user_id: str) -> list[SessionSummary]:
        index_key = self._user_index_key(user_id)
        digests = await self.redis.smembers(index_key)
        summaries: list[SessionSummary] = []
        stale: list[str] = []

        for digest in digests:
            if isinstance(digest, bytes):
                digest = digest.decode("utf-8")
            raw = await self.redis.get(self._session_key_from_digest(digest))
            if not raw:
                stale.append(digest)
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(raw)
            summaries.append(SessionSummary(
                session_id=digest,
                created_at=payload["created_at"],
                last_seen_at=payload["last_seen_at"],
            ))

        if stale:
            await self.redis.srem(index_key, *stale)

        summaries.sort(key=lambda s: s.last_seen_at, reverse=True)
        return summaries

    async def revoke(self, user_id: str, session_id: str) -> bool:
        """Revokes a single session by its public id (digest), only if it
        belongs to `user_id` -- prevents one user from revoking another's
        session by guessing/sharing a digest."""
        index_key = self._user_index_key(user_id)
        is_member = await self.redis.sismember(index_key, session_id)
        if not is_member:
            return False
        await self.redis.delete(self._session_key_from_digest(session_id))
        await self.redis.srem(index_key, session_id)
        return True

    async def revoke_all_for_user(self, user_id: str, *, except_session_id: str | None = None) -> int:
        index_key = self._user_index_key(user_id)
        digests = await self.redis.smembers(index_key)
        removed = 0

        for digest in digests:
            if isinstance(digest, bytes):
                digest = digest.decode("utf-8")
            if digest == except_session_id:
                continue
            await self.redis.delete(self._session_key_from_digest(digest))
            await self.redis.srem(index_key, digest)
            removed += 1

        return removed
