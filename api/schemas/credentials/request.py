"""Request schemas for credentials endpoints."""

from pydantic import BaseModel, Field


class CredentialCreateRequest(BaseModel):
    """Запрос на создание учетных данных."""

    platform: str = Field(..., description="Платформа (zoom, youtube, vk)")
    account_name: str | None = Field(None, description="Имя аккаунта (для нескольких аккаунтов)")
    credentials: dict = Field(..., description="Учетные данные платформы")


class CredentialUpdateRequest(BaseModel):
    """Запрос на обновление учетных данных."""

    credentials: dict = Field(..., description="Обновленные учетные данные")
