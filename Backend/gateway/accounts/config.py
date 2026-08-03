from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    database_url: str
    redis_url: str
    cookie_secret: str
    cookie_secure: bool
    cookie_domain: str | None
    session_ttl_seconds: int
    visitor_ttl_seconds: int
    email_verification_ttl_seconds: int = 86400
    password_reset_ttl_seconds: int = 3600
    visitor_cookie_name: str = "kg_visitor"
    session_cookie_name: str = "kg_session"

    @classmethod
    def from_env(cls) -> "AuthSettings":
        domain = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
        return cls(
            enabled=_as_bool(os.getenv("AUTH_ENABLED"), default=False),
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql+asyncpg://kg:kg@postgres:5432/knowledge_graph",
            ),
            redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
            cookie_secret=os.getenv(
                "AUTH_COOKIE_SECRET",
                "development-only-change-this-cookie-secret",
            ),
            cookie_secure=_as_bool(os.getenv("AUTH_COOKIE_SECURE"), default=False),
            cookie_domain=domain,
            session_ttl_seconds=int(os.getenv("AUTH_SESSION_TTL_SECONDS", "2592000")),
            visitor_ttl_seconds=int(os.getenv("AUTH_VISITOR_TTL_SECONDS", "7776000")),
            email_verification_ttl_seconds=int(
                os.getenv("EMAIL_VERIFICATION_TTL_SECONDS", "86400")
            ),
            password_reset_ttl_seconds=int(os.getenv("PASSWORD_RESET_TTL_SECONDS", "3600")),
        )
