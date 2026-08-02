from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
import traceback
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from .config import MiddlewareSettings
from .context import request_id_context
from .errors import error_payload
from .rate_limit import RateLimitResult


logger = logging.getLogger("gateway.access")
logger.setLevel(logging.INFO)
if not any(getattr(handler, "_gateway_json_handler", False) for handler in logger.handlers):
    json_handler = logging.StreamHandler(sys.stdout)
    json_handler.setFormatter(logging.Formatter("%(message)s"))
    json_handler._gateway_json_handler = True
    logger.addHandler(json_handler)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
BODY_METHODS = {"POST", "PUT", "PATCH"}


class PayloadTooLarge(Exception):
    pass


class PlatformMiddleware:
    def __init__(self, app, settings: MiddlewareSettings, rate_limiter=None):
        self.app = app
        self.settings = settings
        self.rate_limiter = rate_limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = self._request_id(headers.get("x-request-id"))
        context_token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        status_code = 500
        rate_result = None
        response_started = False

        async def send_with_headers(message):
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
                response_headers["X-Content-Type-Options"] = "nosniff"
                origin = (headers.get("origin") or "").rstrip("/")
                if origin and origin in self.settings.allowed_origins:
                    response_headers["Access-Control-Allow-Origin"] = origin
                    response_headers["Access-Control-Allow-Credentials"] = "true"
                    response_headers.add_vary_header("Origin")
                if scope["path"].startswith("/api/auth/"):
                    response_headers["Cache-Control"] = "no-store"
                if rate_result is not None:
                    response_headers["RateLimit-Limit"] = str(rate_result.limit)
                    response_headers["RateLimit-Remaining"] = str(rate_result.remaining)
                    response_headers["RateLimit-Reset"] = str(rate_result.retry_after)
            await send(message)

        try:
            early_response = self._security_response(scope, headers, request_id)
            if early_response is not None:
                status_code = early_response.status_code
                await early_response(scope, receive, send_with_headers)
                return

            if self.rate_limiter is not None and self.settings.rate_limit_enabled:
                try:
                    rate_result = await self._check_rate_limit(scope, headers)
                except Exception as exc:
                    logger.error(
                        json.dumps(
                            {
                                "event": "rate_limit_unavailable",
                                "request_id": request_id,
                                "path": scope["path"],
                                **self._safe_exception_metadata(exc),
                            }
                        )
                    )
                    response = JSONResponse(
                        error_payload(
                            status_code=503,
                            detail="İstek güvenlik kontrolü şu anda kullanılamıyor.",
                            request_id=request_id,
                            code="RATE_LIMIT_UNAVAILABLE",
                        ),
                        status_code=503,
                    )
                    status_code = 503
                    await response(scope, receive, send_with_headers)
                    return
                if rate_result is not None and not rate_result.allowed:
                    response = JSONResponse(
                        error_payload(
                            status_code=429,
                            detail="Çok fazla istek gönderildi. Lütfen daha sonra tekrar deneyin.",
                            request_id=request_id,
                        ),
                        status_code=429,
                        headers={"Retry-After": str(rate_result.retry_after)},
                    )
                    status_code = 429
                    await response(scope, receive, send_with_headers)
                    return

            await self.app(
                scope,
                self._limited_receive(receive),
                send_with_headers,
            )
        except PayloadTooLarge:
            response = JSONResponse(
                error_payload(
                    status_code=413,
                    detail="İstek gövdesi izin verilen boyutu aşıyor.",
                    request_id=request_id,
                ),
                status_code=413,
            )
            status_code = 413
            await response(scope, receive, send_with_headers)
        except Exception as exc:
            logger.error(
                json.dumps(
                    {
                        "event": "unhandled_request_error",
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": scope["path"],
                        **self._safe_exception_metadata(exc),
                    },
                    ensure_ascii=False,
                )
            )
            if response_started:
                raise
            response = JSONResponse(
                error_payload(
                    status_code=500,
                    detail="İstek işlenirken beklenmeyen bir hata oluştu.",
                    request_id=request_id,
                ),
                status_code=500,
            )
            status_code = 500
            await response(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "path": scope["path"],
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "client": self._client_key(scope, headers),
                    },
                    ensure_ascii=False,
                )
            )
            request_id_context.reset(context_token)

    def _security_response(self, scope, headers: Headers, request_id: str):
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.settings.max_request_bytes:
                    return JSONResponse(
                        error_payload(
                            status_code=413,
                            detail="İstek gövdesi izin verilen boyutu aşıyor.",
                            request_id=request_id,
                        ),
                        status_code=413,
                    )
            except ValueError:
                return JSONResponse(
                    error_payload(
                        status_code=400,
                        detail="Geçersiz Content-Length başlığı.",
                        request_id=request_id,
                    ),
                    status_code=400,
                )

        has_body = content_length not in {None, "0"}
        if (
            scope["method"] in BODY_METHODS
            and scope["path"].startswith("/api/")
            and has_body
            and not (headers.get("content-type") or "").lower().startswith("application/json")
        ):
            return JSONResponse(
                error_payload(
                    status_code=415,
                    detail="Bu endpoint application/json içerik türü bekliyor.",
                    request_id=request_id,
                ),
                status_code=415,
            )

        origin = (headers.get("origin") or "").rstrip("/")
        if (
            scope["method"] in UNSAFE_METHODS
            and origin
            and origin not in self.settings.allowed_origins
        ):
            return JSONResponse(
                error_payload(
                    status_code=403,
                    detail="İstek kaynağına izin verilmiyor.",
                    request_id=request_id,
                    code="ORIGIN_NOT_ALLOWED",
                ),
                status_code=403,
            )
        return None

    def _limited_receive(self, receive):
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.settings.max_request_bytes:
                    raise PayloadTooLarge
            return message

        return limited_receive

    async def _check_rate_limit(self, scope, headers: Headers) -> RateLimitResult | None:
        path = scope["path"]
        if scope["method"] == "OPTIONS" or path.startswith("/api/health/"):
            return None

        if path in {"/api/auth/login", "/api/auth/register"}:
            bucket, limit = "auth", self.settings.auth_rate_limit
        elif path == "/api/extract":
            bucket, limit = "extract", self.settings.extract_rate_limit
        elif path.startswith("/api/"):
            bucket, limit = "general", self.settings.general_rate_limit
        else:
            return None

        actor = self._actor_key(scope, headers)
        key = f"rate:{bucket}:{actor}"
        return await self.rate_limiter.check(
            key,
            limit,
            self.settings.rate_limit_window_seconds,
        )

    def _actor_key(self, scope, headers: Headers) -> str:
        # The anonymous cookie is user-controlled at this layer. Using it as the
        # sole key would let a client bypass limits by rotating cookie values.
        return self._hash(self._client_ip(scope, headers))

    def _client_key(self, scope, headers: Headers) -> str:
        return self._hash(self._client_ip(scope, headers))

    def _client_ip(self, scope, headers: Headers) -> str:
        if self.settings.trust_proxy_headers:
            forwarded = headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        client = scope.get("client")
        return str(client[0]) if client else "unknown"

    def _hash(self, value: str) -> str:
        material = f"{self.settings.log_hash_salt}:{value}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()[:16]

    @staticmethod
    def _safe_exception_metadata(exc: Exception) -> dict:
        frames = traceback.extract_tb(exc.__traceback__)[-8:]
        return {
            "exception_type": type(exc).__name__,
            "frames": [
                {"file": frame.filename.rsplit("/", 1)[-1], "line": frame.lineno, "function": frame.name}
                for frame in frames
            ],
        }

    @staticmethod
    def _request_id(candidate: str | None) -> str:
        if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
        return f"req_{uuid.uuid4().hex}"
