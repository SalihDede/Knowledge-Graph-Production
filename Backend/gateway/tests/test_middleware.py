from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gateway_middleware.config import MiddlewareSettings
from gateway_middleware.rate_limit import RateLimitResult
from gateway_middleware.setup import install_error_handlers, install_platform_middleware


class EchoBody(BaseModel):
    value: str


class MemoryRateLimiter:
    def __init__(self):
        self.counts: dict[str, int] = {}

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        current = self.counts.get(key, 0) + 1
        self.counts[key] = current
        return RateLimitResult(
            allowed=current <= limit,
            limit=limit,
            remaining=max(limit - current, 0),
            retry_after=window_seconds,
        )


class FailingRateLimiter:
    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        raise ConnectionError("redis password must never leak")


def settings(**overrides) -> MiddlewareSettings:
    values = {
        "allowed_origins": ("http://localhost:3000",),
        "max_request_bytes": 128,
        "trust_proxy_headers": True,
        "log_hash_salt": "test-log-salt",
        "redis_url": "redis://unused",
        "rate_limit_enabled": True,
        "rate_limit_window_seconds": 60,
        "general_rate_limit": 2,
        "auth_rate_limit": 1,
        "extract_rate_limit": 1,
    }
    values.update(overrides)
    return MiddlewareSettings(**values)


def make_app(*, middleware_settings=None, limiter=None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/ok")
    async def ok():
        return {"ok": True}

    @app.post("/api/echo")
    async def echo(body: EchoBody):
        return body

    @app.get("/api/bad")
    async def bad():
        raise HTTPException(status_code=400, detail="Kontrollü hata")

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("database-password-must-not-leak")

    install_error_handlers(app)
    install_platform_middleware(
        app,
        middleware_settings or settings(),
        rate_limiter=limiter or MemoryRateLimiter(),
    )
    return app


def test_request_id_is_generated_preserved_and_returned_in_errors() -> None:
    client = TestClient(make_app(middleware_settings=settings(general_rate_limit=20)))

    generated = client.get("/api/ok")
    preserved = client.get("/api/ok", headers={"X-Request-ID": "client-request-42"})
    invalid = client.get("/api/bad", headers={"X-Request-ID": "invalid request id"})

    assert generated.headers["x-request-id"].startswith("req_")
    assert preserved.headers["x-request-id"] == "client-request-42"
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Kontrollü hata"
    assert invalid.json()["error"]["request_id"] == invalid.headers["x-request-id"]


def test_unhandled_errors_are_sanitised_and_logged(caplog) -> None:
    client = TestClient(make_app())
    caplog.set_level(logging.INFO)

    response = client.get("/api/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "database-password" not in str(response.json())
    assert "unhandled_request_error" in caplog.text
    assert "database-password" not in caplog.text


def test_body_size_content_type_and_origin_are_enforced() -> None:
    client = TestClient(make_app(middleware_settings=settings(general_rate_limit=20)))

    too_large = client.post(
        "/api/echo",
        content='{"value":"' + ("x" * 200) + '"}',
        headers={"Content-Type": "application/json"},
    )
    wrong_type = client.post(
        "/api/echo",
        content="value=test",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    blocked_origin = client.post(
        "/api/echo",
        json={"value": "ok"},
        headers={"Origin": "https://attacker.example"},
    )
    allowed_origin = client.post(
        "/api/echo",
        json={"value": "ok"},
        headers={"Origin": "http://localhost:3000"},
    )

    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert wrong_type.status_code == 415
    assert blocked_origin.status_code == 403
    assert blocked_origin.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert allowed_origin.status_code == 200


def test_rate_limit_has_headers_and_blocks_excess_requests() -> None:
    client = TestClient(make_app())

    first = client.get("/api/ok")
    second = client.get("/api/ok")
    blocked = client.get("/api/ok")

    assert first.status_code == 200
    assert first.headers["ratelimit-limit"] == "2"
    assert second.headers["ratelimit-remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_rotating_visitor_cookie_does_not_bypass_auth_rate_limit() -> None:
    client = TestClient(make_app())

    first = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "irrelevant"},
        headers={"Cookie": "kg_visitor=first-value"},
    )
    blocked = client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "irrelevant"},
        headers={"Cookie": "kg_visitor=rotated-value"},
    )

    assert first.status_code == 404
    assert blocked.status_code == 429


def test_preflight_does_not_consume_quota_and_early_errors_include_cors() -> None:
    client = TestClient(make_app())

    preflight = client.options(
        "/api/ok",
        headers={"Origin": "http://localhost:3000"},
    )
    first = client.get(
        "/api/ok",
        headers={"Origin": "http://localhost:3000"},
    )
    second = client.get("/api/ok")
    blocked = client.get(
        "/api/ok",
        headers={"Origin": "http://localhost:3000"},
    )

    assert preflight.status_code == 405
    assert first.status_code == 200
    assert second.status_code == 200
    assert blocked.status_code == 429
    assert blocked.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert blocked.headers["access-control-allow-credentials"] == "true"


def test_rate_limit_failure_is_closed_without_leaking_error(caplog) -> None:
    client = TestClient(make_app(limiter=FailingRateLimiter()))
    caplog.set_level(logging.INFO)

    response = client.get("/api/ok")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"
    assert "redis password" not in str(response.json())
    assert "rate_limit_unavailable" in caplog.text
    assert "redis password" not in caplog.text


def test_access_log_never_contains_request_body(caplog) -> None:
    client = TestClient(make_app())
    caplog.set_level(logging.INFO, logger="gateway.access")

    response = client.post("/api/echo", json={"value": "super-secret-body"})

    assert response.status_code == 200
    assert "http_request" in caplog.text
    assert "super-secret-body" not in caplog.text
