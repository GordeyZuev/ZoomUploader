"""Схемы для источников данных."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class InputSourceBase(BaseModel):
    """Базовая схема для источника."""

    name: str = Field(..., min_length=1, max_length=255, description="Название источника")
    description: str | None = Field(None, max_length=1000, description="Описание источника")
    source_type: Literal["ZOOM", "YANDEX_DISK", "LOCAL", "GOOGLE_DRIVE", "DROPBOX"] = Field(
        ..., description="Тип источника"
    )
    config: dict[str, Any] | None = Field(None, description="Конфигурация источника")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Валидация названия источника."""
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict[str, Any] | None, info) -> dict[str, Any] | None:
        """Валидация конфигурации в зависимости от типа источника."""
        if v is None:
            return v

        source_type = info.data.get("source_type")

        if source_type == "ZOOM":
            required_fields = ["account_id"]
            for field in required_fields:
                if field not in v:
                    raise ValueError(f"Для источника ZOOM требуется поле: {field}")

        elif source_type == "GOOGLE_DRIVE":
            required_fields = ["folder_id"]
            for field in required_fields:
                if field not in v:
                    raise ValueError(f"Для источника GOOGLE_DRIVE требуется поле: {field}")

        elif source_type == "LOCAL":
            required_fields = ["path"]
            for field in required_fields:
                if field not in v:
                    raise ValueError(f"Для источника LOCAL требуется поле: {field}")

        return v


class InputSourceCreate(InputSourceBase):
    """Схема для создания источника."""

    credential_id: int | None = Field(None, description="ID credentials (если требуется)")


class InputSourceUpdate(BaseModel):
    """Схема для обновления источника."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    credential_id: int | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class InputSourceResponse(InputSourceBase):
    """Схема ответа для источника."""

    id: int
    user_id: int
    credential_id: int | None
    is_active: bool
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

