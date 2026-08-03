from __future__ import annotations

import hashlib
import secrets

from pwdlib import PasswordHash


_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_session_token() -> str:
    return secrets.token_urlsafe(48)


def generate_verification_token() -> str:
    """Opaque one-time token for email verification / password reset links.
    Only its digest (see token_digest) is ever persisted."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
