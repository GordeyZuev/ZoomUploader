"""Pydantic схемы для токенов."""

from datetime import datetime

from pydantic import BaseModel, Field


class RefreshTokenBase(BaseModel):
    """Базовая схема refresh токена."""

    token: str


class RefreshTokenCreate(RefreshTokenBase):
    """Схема для создания refresh токена."""

    user_id: int
    expires_at: datetime


class RefreshTokenInDB(RefreshTokenBase):
    """Схема refresh токена в БД."""

    id: int
    user_id: int
    expires_at: datetime
    is_revoked: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class TokenPair(BaseModel):
    """Пара токенов (access + refresh)."""

    access_token: str = Field(..., description="Access токен")
    refresh_token: str = Field(..., description="Refresh токен")
    token_type: str = Field(default="bearer", description="Тип токена")
    expires_in: int = Field(..., description="Время жизни access токена в секундах")

