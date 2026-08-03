from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import Uuid as UuidType
from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.exc import IntegrityError

import storage
from .models import AnonymousVisitor, AuthToken, AuthTokenPurpose, User, utc_now
from .runtime import AuthRuntime
from .schemas import (
    AccountDeleteRequest,
    EmailVerificationConfirmRequest,
    IdentityResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    RegisterRequest,
    SessionSummaryResponse,
    UserResponse,
)
from .security import (
    generate_verification_token,
    hash_password,
    token_digest,
    verify_password,
)
from .store import SessionData


logger = logging.getLogger(__name__)
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


def _require_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Giriş yapmanız gerekiyor")
    return user


def _deliver_email_placeholder(*, purpose: str, to_email: str, token: str) -> None:
    """No email provider is wired up yet -- this logs the token instead of
    sending a real message. Deliberate development-only stand-in: replace
    with a real provider (SMTP/Resend/etc.) before a real deployment, since
    anyone with log access could otherwise complete a password reset or
    email verification for any account."""
    logger.info(
        json.dumps(
            {
                "event": "auth_email_placeholder",
                "purpose": purpose,
                "to_email": to_email,
                "token": token,
            },
            ensure_ascii=False,
        )
    )


async def _issue_token(db, *, user_id: uuid.UUID, purpose: AuthTokenPurpose, ttl_seconds: int) -> str:
    # Invalidate any previous unused token of the same purpose first, so a
    # user only ever has one live verification/reset link at a time.
    await db.execute(
        delete(AuthToken).where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
    )
    token = generate_verification_token()
    db.add(AuthToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=token_digest(token),
        expires_at=utc_now() + timedelta(seconds=ttl_seconds),
    ))
    await db.commit()
    return token


def _as_aware_utc(value: datetime) -> datetime:
    # SQLite (used in tests) returns naive datetimes even for
    # DateTime(timezone=True) columns; Postgres returns aware ones. Both
    # always represent UTC (see accounts.models.utc_now), so a naive value
    # just needs the tzinfo attached before comparing against utc_now().
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _consume_token(db, *, token: str, purpose: AuthTokenPurpose) -> User | None:
    record = await db.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == token_digest(token),
            AuthToken.purpose == purpose,
        )
    )
    if record is None or record.used_at is not None or _as_aware_utc(record.expires_at) < utc_now():
        return None
    user = await db.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    record.used_at = utc_now()
    await db.commit()
    return user


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


@router.post("/email/verification/request", response_model=MessageResponse)
async def request_email_verification(request: Request) -> MessageResponse:
    runtime = _runtime(request)
    user = _require_user(request)

    if user.email_verified_at is not None:
        return MessageResponse(detail="E-posta zaten doğrulanmış")

    async with runtime.sessions() as db:
        token = await _issue_token(
            db,
            user_id=user.id,
            purpose=AuthTokenPurpose.email_verification,
            ttl_seconds=runtime.settings.email_verification_ttl_seconds,
        )
    _deliver_email_placeholder(purpose="email_verification", to_email=user.email, token=token)
    return MessageResponse(detail="Doğrulama bağlantısı gönderildi")


@router.post("/email/verification/confirm", response_model=MessageResponse)
async def confirm_email_verification(
    body: EmailVerificationConfirmRequest, request: Request,
) -> MessageResponse:
    runtime = _runtime(request)
    async with runtime.sessions() as db:
        user = await _consume_token(db, token=body.token, purpose=AuthTokenPurpose.email_verification)
        if user is None:
            raise HTTPException(status_code=400, detail="Doğrulama bağlantısı geçersiz veya süresi dolmuş")
        user.email_verified_at = utc_now()
        await db.commit()
    return MessageResponse(detail="E-posta doğrulandı")


@router.post("/password/reset/request", response_model=MessageResponse)
async def request_password_reset(body: PasswordResetRequest, request: Request) -> MessageResponse:
    runtime = _runtime(request)
    email = _normalise_email(str(body.email))

    async with runtime.sessions() as db:
        user = await db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
        if user is not None:
            token = await _issue_token(
                db,
                user_id=user.id,
                purpose=AuthTokenPurpose.password_reset,
                ttl_seconds=runtime.settings.password_reset_ttl_seconds,
            )
            _deliver_email_placeholder(purpose="password_reset", to_email=user.email, token=token)

    # Always the same response whether or not the email is registered, so
    # this endpoint can't be used to enumerate accounts.
    return MessageResponse(detail="Bu e-posta adresine kayıtlı bir hesap varsa, sıfırlama bağlantısı gönderildi")


@router.post("/password/reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(body: PasswordResetConfirmRequest, request: Request) -> MessageResponse:
    runtime = _runtime(request)
    new_hash = await asyncio.to_thread(hash_password, body.new_password)

    async with runtime.sessions() as db:
        user = await _consume_token(db, token=body.token, purpose=AuthTokenPurpose.password_reset)
        if user is None:
            raise HTTPException(status_code=400, detail="Sıfırlama bağlantısı geçersiz veya süresi dolmuş")
        user.password_hash = new_hash
        await db.commit()
        user_id = str(user.id)

    # A password reset invalidates every existing session -- if the reset
    # was triggered because credentials leaked, staying logged in anywhere
    # else is exactly the risk this closes.
    await runtime.session_store.revoke_all_for_user(user_id)
    return MessageResponse(detail="Şifre güncellendi, lütfen tekrar giriş yapın")


@router.get("/sessions", response_model=list[SessionSummaryResponse])
async def list_sessions(request: Request) -> list[SessionSummaryResponse]:
    runtime = _runtime(request)
    user = _require_user(request)
    current_token = getattr(request.state, "auth_session_token", None)
    current_digest = token_digest(current_token) if current_token else None

    summaries = await runtime.session_store.list_for_user(str(user.id))
    return [
        SessionSummaryResponse(
            id=summary.session_id,
            created_at=summary.created_at,
            last_seen_at=summary.last_seen_at,
            is_current=summary.session_id == current_digest,
        )
        for summary in summaries
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(session_id: str, request: Request) -> Response:
    runtime = _runtime(request)
    user = _require_user(request)
    revoked = await runtime.session_store.revoke(str(user.id), session_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Oturum bulunamadı")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/sessions", response_model=MessageResponse)
async def revoke_all_sessions(
    request: Request, response: Response, include_current: bool = False,
) -> MessageResponse:
    runtime = _runtime(request)
    user = _require_user(request)
    current_token = getattr(request.state, "auth_session_token", None)
    current_digest = token_digest(current_token) if current_token else None
    except_digest = None if include_current else current_digest

    count = await runtime.session_store.revoke_all_for_user(str(user.id), except_session_id=except_digest)

    if include_current:
        response.delete_cookie(
            runtime.settings.session_cookie_name,
            path="/",
            domain=runtime.settings.cookie_domain,
        )

    return MessageResponse(detail=f"{count} oturum kapatıldı")


@router.delete("/account", response_model=MessageResponse)
async def delete_account(
    body: AccountDeleteRequest, request: Request, response: Response,
) -> MessageResponse:
    runtime = _runtime(request)
    user = _require_user(request)

    valid_password = await asyncio.to_thread(verify_password, body.password, user.password_hash)
    if not valid_password:
        raise HTTPException(status_code=401, detail="Şifre hatalı")

    user_id = user.id
    async with runtime.sessions() as db:
        # Collected before the delete below cascades away the documents
        # rows that reference them: MinIO objects are not covered by the
        # database's ON DELETE CASCADE and need their own best-effort
        # cleanup afterwards. Raw SQL (not the documents ORM models) is
        # used deliberately here, to avoid accounts/ depending on
        # documents/ at import time -- see worker/ingestion_tasks.py and
        # documents/routes.py for the circular-import hazard that pattern
        # risks re-creating.
        result = await db.execute(
            text(
                """
                SELECT d.storage_key
                FROM documents d
                JOIN workspaces w ON w.id = d.workspace_id
                WHERE w.owner_user_id = :user_id
                  AND d.source_type = 'pdf'
                  AND d.storage_key IS NOT NULL
                """
            ).bindparams(bindparam("user_id", type_=UuidType())),
            {"user_id": user_id},
        )
        storage_keys = [row[0] for row in result.all()]

        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()

    await runtime.session_store.revoke_all_for_user(str(user_id))
    response.delete_cookie(
        runtime.settings.session_cookie_name,
        path="/",
        domain=runtime.settings.cookie_domain,
    )

    for storage_key in storage_keys:
        try:
            storage.delete_object(storage_key)
        except storage.StorageError:
            logger.warning(
                "Could not delete storage object %s for a deleted account", storage_key, exc_info=True,
            )

    return MessageResponse(detail="Hesap silindi")
