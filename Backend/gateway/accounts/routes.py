from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import AnonymousVisitor, User, utc_now
from .runtime import AuthRuntime
from .schemas import IdentityResponse, LoginRequest, RegisterRequest, UserResponse
from .security import hash_password, verify_password
from .store import SessionData


router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


def _runtime(request: Request) -> AuthRuntime:
    return request.app.state.accounts


def _normalise_email(email: str) -> str:
    return email.strip().casefold()


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
    )


def _identity_response(request: Request, user: User | None = None) -> IdentityResponse:
    resolved_user = user if user is not None else getattr(request.state, "user", None)
    return IdentityResponse(
        authenticated=resolved_user is not None,
        visitor_id=str(request.state.visitor_id),
        user=_user_response(resolved_user) if resolved_user is not None else None,
    )


def _set_session_cookie(response: Response, runtime: AuthRuntime, token: str) -> None:
    settings = runtime.settings
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain,
    )


async def _claim_visitor(runtime: AuthRuntime, visitor_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with runtime.sessions() as db:
        visitor = await db.get(AnonymousVisitor, visitor_id)
        if visitor is None:
            raise HTTPException(status_code=409, detail="Anonim oturum bulunamadı")
        if visitor.claimed_by_user_id not in {None, user_id}:
            raise HTTPException(status_code=409, detail="Anonim oturum başka bir hesaba bağlı")
        visitor.claimed_by_user_id = user_id
        visitor.claimed_at = visitor.claimed_at or utc_now()
        visitor.last_seen_at = utc_now()
        await db.commit()


async def _create_login_session(
    request: Request,
    response: Response,
    user: User,
) -> None:
    runtime = _runtime(request)
    visitor_id = request.state.visitor_id
    await _claim_visitor(runtime, visitor_id, user.id)
    token = await runtime.session_store.create(
        SessionData(user_id=str(user.id), visitor_id=str(visitor_id))
    )
    _set_session_cookie(response, runtime, token)


@router.get("/me", response_model=IdentityResponse)
async def me(request: Request) -> IdentityResponse:
    return _identity_response(request)


@router.post("/register", response_model=IdentityResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
) -> IdentityResponse:
    runtime = _runtime(request)
    email = _normalise_email(str(body.email))
    password_hash = await asyncio.to_thread(hash_password, body.password)

    async with runtime.sessions() as db:
        existing = await db.scalar(select(User.id).where(User.email == email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Bu e-posta adresi zaten kullanımda")

        user = User(
            email=email,
            display_name=body.display_name,
            password_hash=password_hash,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Bu e-posta adresi zaten kullanımda") from exc
        await db.refresh(user)

    await _create_login_session(request, response, user)
    return _identity_response(request, user)


@router.post("/login", response_model=IdentityResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
) -> IdentityResponse:
    runtime = _runtime(request)
    email = _normalise_email(str(body.email))

    async with runtime.sessions() as db:
        user = await db.scalar(select(User).where(User.email == email))

    stored_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    valid_password = await asyncio.to_thread(verify_password, body.password, stored_hash)
    if user is None or not valid_password or not user.is_active:
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı")

    await _create_login_session(request, response, user)
    return _identity_response(request, user)


@router.post("/logout", response_model=IdentityResponse)
async def logout(request: Request, response: Response) -> IdentityResponse:
    runtime = _runtime(request)
    token = getattr(request.state, "auth_session_token", None)
    if token:
        await runtime.session_store.delete(token)
    response.delete_cookie(
        runtime.settings.session_cookie_name,
        path="/",
        domain=runtime.settings.cookie_domain,
    )
    return IdentityResponse(
        authenticated=False,
        visitor_id=str(request.state.visitor_id),
        user=None,
    )
