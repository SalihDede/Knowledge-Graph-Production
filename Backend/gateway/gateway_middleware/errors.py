from __future__ import annotations

from typing import Any


STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    502: "UPSTREAM_SERVICE_ERROR",
    503: "SERVICE_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}


def error_payload(
    *,
    status_code: int,
    detail: Any,
    request_id: str,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "detail": detail,
        "error": {
            "code": code or STATUS_CODES.get(status_code, "INTERNAL_SERVER_ERROR"),
            "request_id": request_id,
        },
    }
