from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class MiddlewareSettings:
    allowed_origins: tuple[str, ...]
    max_request_bytes: int
    trust_proxy_headers: bool
    log_hash_salt: str
    redis_url: str
    rate_limit_enabled: bool
    rate_limit_window_seconds: int
    general_rate_limit: int
    auth_rate_limit: int
    extract_rate_limit: int

    @classmethod
    def from_env(cls) -> "MiddlewareSettings":
        return cls(
            allowed_origins=_csv(
                os.getenv(
                    "ALLOWED_ORIGINS",
                    "http://localhost:3000,http://localhost:5173",
                )
            ),
            max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", "2097152")),
            trust_proxy_headers=_as_bool(os.getenv("TRUST_PROXY_HEADERS"), True),
            log_hash_salt=os.getenv("LOG_HASH_SALT", "development-log-hash-salt"),
            redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
            rate_limit_enabled=_as_bool(os.getenv("RATE_LIMIT_ENABLED"), False),
            rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
            general_rate_limit=int(os.getenv("RATE_LIMIT_GENERAL_REQUESTS", "120")),
            auth_rate_limit=int(os.getenv("RATE_LIMIT_AUTH_REQUESTS", "10")),
            extract_rate_limit=int(os.getenv("RATE_LIMIT_EXTRACT_REQUESTS", "10")),
        )
