"""Схемы ответов для аутентификации."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class TokenResponse(BaseModel):
    """Ответ с токенами."""

    access_token: str = Field(..., description="Access токен")
    refresh_token: str = Field(..., description="Refresh токен")
    token_type: str = Field(default="bearer", description="Тип токена")
    expires_in: int = Field(..., description="Время жизни access токена в секундах")


class UserResponse(BaseModel):
    """Ответ с информацией о пользователе."""

    id: int = Field(..., description="ID пользователя")
    email: EmailStr = Field(..., description="Email")
    full_name: str | None = Field(None, description="Полное имя")
    is_active: bool = Field(..., description="Активен ли аккаунт")
    is_verified: bool = Field(..., description="Подтвержден ли email")
    is_superuser: bool = Field(..., description="Суперпользователь")
    created_at: datetime = Field(..., description="Дата создания")
    last_login_at: datetime | None = Field(None, description="Последний вход")

    class Config:
        from_attributes = True


class MeResponse(BaseModel):
    """Ответ с информацией о текущем пользователе."""

    user: UserResponse = Field(..., description="Информация о пользователе")
    quotas: dict | None = Field(None, description="Квоты пользователя")
