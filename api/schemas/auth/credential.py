"""Pydantic схемы для учетных данных пользователей."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserCredentialBase(BaseModel):
    """Базовая схема учетных данных."""

    platform: str = Field(..., max_length=50, description="Платформа (zoom, youtube, gdrive)")
    account_name: str | None = Field(None, max_length=255, description="Имя аккаунта (для нескольких аккаунтов)")


class UserCredentialCreate(UserCredentialBase):
    """Схема для создания учетных данных."""

    user_id: int
    encrypted_data: str = Field(..., description="Зашифрованные данные")


class UserCredentialUpdate(BaseModel):
    """Схема для обновления учетных данных."""

    encrypted_data: str | None = None
    is_active: bool | None = None


class UserCredentialInDB(UserCredentialBase):
    """Схема учетных данных в БД."""

    id: int
    user_id: int
    encrypted_data: str
    is_active: bool = True
    created_at: datetime
    last_used_at: datetime | None = None

    class Config:
        from_attributes = True


class UserCredentialResponse(BaseModel):
    """Схема ответа с учетными данными (без зашифрованных данных)."""

    id: int
    platform: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    class Config:
        from_attributes = True

