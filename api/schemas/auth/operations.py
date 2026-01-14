"""Schemas for auth operations."""

from pydantic import BaseModel


class LogoutResponse(BaseModel):
    """Результат logout."""

    message: str


class LogoutAllResponse(BaseModel):
    """Результат logout от всех устройств."""

    message: str
    revoked_tokens: int
