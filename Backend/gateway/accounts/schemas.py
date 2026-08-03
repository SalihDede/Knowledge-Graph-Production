from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=2, max_length=120)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Görünen ad en az 2 karakter olmalıdır")
        return cleaned


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    email_verified: bool


class IdentityResponse(BaseModel):
    authenticated: bool
    visitor_id: str
    user: UserResponse | None = None


class MessageResponse(BaseModel):
    detail: str


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=128)


class SessionSummaryResponse(BaseModel):
    id: str
    created_at: datetime
    last_seen_at: datetime
    is_current: bool


class AccountDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
