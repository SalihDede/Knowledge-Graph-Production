from __future__ import annotations

import logging
import uuid

from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .models import AnonymousVisitor, User
from .runtime import AuthRuntime


logger = logging.getLogger(__name__)


class IdentityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, runtime: AuthRuntime):
        super().__init__(app)
        self.runtime = runtime

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/health/"):
            return await call_next(request)

        settings = self.runtime.settings
        visitor_id, set_visitor_cookie = await self._resolve_visitor(request)
        user = None
        session_token = request.cookies.get(settings.session_cookie_name)
        clear_session_cookie = False

        if session_token:
            try:
                session_data = await self.runtime.session_store.get(session_token)
            except Exception:
                logger.exception("Authentication session lookup failed")
                session_data = None
            if session_data:
                async with self.runtime.sessions() as db:
                    user = await db.scalar(
                        select(User).where(
                            User.id == uuid.UUID(session_data.user_id),
                            User.is_active.is_(True),
                        )
                    )
            if user is None:
                clear_session_cookie = True

        request.state.visitor_id = visitor_id
        request.state.user = user
        request.state.auth_session_token = session_token if user is not None else None

        response = await call_next(request)
        if set_visitor_cookie:
            signed = self.runtime.visitor_signer.dumps(str(visitor_id), salt="visitor")
            response.set_cookie(
                settings.visitor_cookie_name,
                signed,
                max_age=settings.visitor_ttl_seconds,
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
                path="/",
                domain=settings.cookie_domain,
            )
        if clear_session_cookie:
            response.delete_cookie(
                settings.session_cookie_name,
                path="/",
                domain=settings.cookie_domain,
            )
        return response

    async def _resolve_visitor(self, request: Request) -> tuple[uuid.UUID, bool]:
        settings = self.runtime.settings
        signed = request.cookies.get(settings.visitor_cookie_name)
        visitor_id = None

        if signed:
            try:
                raw_id = self.runtime.visitor_signer.loads(
                    signed,
                    salt="visitor",
                    max_age=settings.visitor_ttl_seconds,
                )
                visitor_id = uuid.UUID(str(raw_id))
            except (BadSignature, SignatureExpired, ValueError):
                visitor_id = None

        async with self.runtime.sessions() as db:
            if visitor_id is not None:
                visitor = await db.get(AnonymousVisitor, visitor_id)
                if visitor is not None:
                    return visitor.id, False

            visitor = AnonymousVisitor()
            db.add(visitor)
            await db.commit()
            await db.refresh(visitor)
            return visitor.id, True
