from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from accounts.security import create_session_token, token_digest
from accounts.store import SessionData, SessionSummary


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _StoredSession:
    user_id: str
    visitor_id: str
    created_at: str
    last_seen_at: str


class MemorySessionStore:
    """In-memory RedisSessionStore stand-in shared by tests that exercise
    accounts/documents routes without a real Redis instance. Mirrors the
    real store's digest-as-public-session-id scheme (see accounts/store.py)
    so route code that compares a request's own session digest against
    list_for_user() results behaves identically against both."""

    def __init__(self):
        self._by_token: dict[str, _StoredSession] = {}

    async def create(self, data: SessionData) -> str:
        token = create_session_token()
        now = _now_iso()
        self._by_token[token] = _StoredSession(
            user_id=data.user_id, visitor_id=data.visitor_id, created_at=now, last_seen_at=now,
        )
        return token

    async def get(self, token: str) -> SessionData | None:
        stored = self._by_token.get(token)
        if stored is None:
            return None
        stored.last_seen_at = _now_iso()
        return SessionData(user_id=stored.user_id, visitor_id=stored.visitor_id)

    async def delete(self, token: str) -> None:
        self._by_token.pop(token, None)

    async def ping(self) -> bool:
        return True

    async def list_for_user(self, user_id: str) -> list[SessionSummary]:
        return [
            SessionSummary(
                session_id=token_digest(token),
                created_at=stored.created_at,
                last_seen_at=stored.last_seen_at,
            )
            for token, stored in self._by_token.items()
            if stored.user_id == user_id
        ]

    async def revoke(self, user_id: str, session_id: str) -> bool:
        for token, stored in list(self._by_token.items()):
            if stored.user_id == user_id and token_digest(token) == session_id:
                del self._by_token[token]
                return True
        return False

    async def revoke_all_for_user(self, user_id: str, *, except_session_id: str | None = None) -> int:
        removed = 0
        for token, stored in list(self._by_token.items()):
            if stored.user_id != user_id:
                continue
            if except_session_id is not None and token_digest(token) == except_session_id:
                continue
            del self._by_token[token]
            removed += 1
        return removed
