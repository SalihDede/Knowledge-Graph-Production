from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.exceptions import HTTPException

from .config import MiddlewareSettings
from .context import request_id_context
from .errors import error_payload
from .middleware import PlatformMiddleware
from .rate_limit import RedisFixedWindowRateLimiter


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            error_payload(
                status_code=exc.status_code,
                detail=jsonable_encoder(exc.detail),
                request_id=request_id_context.get(),
            ),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            error_payload(
                status_code=422,
                detail=jsonable_encoder(exc.errors()),
                request_id=request_id_context.get(),
            ),
            status_code=422,
        )


def install_platform_middleware(
    app: FastAPI,
    settings: MiddlewareSettings,
    rate_limiter=None,
) -> None:
    if rate_limiter is None and settings.rate_limit_enabled:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        rate_limiter = RedisFixedWindowRateLimiter(redis)
    app.add_middleware(
        PlatformMiddleware,
        settings=settings,
        rate_limiter=rate_limiter,
    )
