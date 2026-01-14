"""Schemas for user operations."""

from pydantic import BaseModel


class PasswordChangeResponse(BaseModel):
    """Результат смены пароля."""

    message: str
    detail: str


class AccountDeleteResponse(BaseModel):
    """Результат удаления аккаунта."""

    message: str
    detail: str
