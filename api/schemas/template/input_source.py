"""Схемы для источников данных."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from api.shared.enums import InputPlatform


class InputSourceBase(BaseModel):
    """Базовая схема для источника."""

    name: str = Field(..., min_length=1, max_length=255, description="Название источника")
    description: str | None = Field(None, max_length=1000, description="Описание источника")
    config: dict[str, Any] | None = Field(None, description="Конфигурация источника")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Валидация названия источника."""
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v


class InputSourceCreate(BaseModel):
    """Схема для создания источника."""

    name: str = Field(..., min_length=1, max_length=255, description="Название источника")
    description: str | None = Field(None, max_length=1000, description="Описание источника")
    platform: InputPlatform = Field(..., description="Платформа источника")
    credential_id: int | None = Field(None, description="ID credentials (required для всех кроме LOCAL)")
    config: dict[str, Any] | None = Field(None, description="Конфигурация источника")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @model_validator(mode='after')
    def validate_credentials(self):
        if self.platform != InputPlatform.LOCAL and not self.credential_id:
            raise ValueError(f"Platform {self.platform} requires credential_id")
        return self


class InputSourceUpdate(BaseModel):
    """Схема для обновления источника."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    credential_id: int | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class InputSourceResponse(BaseModel):
    """Схема ответа для источника."""

    id: int
    user_id: int
    name: str
    description: str | None
    source_type: str
    credential_id: int | None
    config: dict[str, Any] | None
    is_active: bool
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

