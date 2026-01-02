"""Схемы для пресетов выгрузки."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class OutputPresetBase(BaseModel):
    """Базовая схема для пресета."""

    name: str = Field(..., min_length=1, max_length=255, description="Название пресета")
    description: str | None = Field(None, max_length=1000, description="Описание пресета")
    platform: Literal["youtube", "vk", "rutube", "gdrive", "yandex_disk"] = Field(..., description="Платформа")
    preset_metadata: dict[str, Any] | None = Field(None, description="Метаданные пресета")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Валидация названия пресета."""
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("preset_metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any] | None, info) -> dict[str, Any] | None:
        """Валидация метаданных в зависимости от платформы."""
        if v is None:
            return {}

        platform = info.data.get("platform")

        if platform == "youtube":
            # Проверяем обязательные поля для YouTube
            if "privacyStatus" in v and v["privacyStatus"] not in ["private", "public", "unlisted"]:
                raise ValueError("privacyStatus должен быть: private, public или unlisted")

            if "categoryId" in v:
                try:
                    cat_id = int(v["categoryId"])
                    if cat_id < 1:
                        raise ValueError("categoryId должен быть положительным числом")
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Неверный categoryId: {e}") from e

        elif platform == "vk":
            # Проверяем обязательные поля для VK
            if "group_id" in v:
                try:
                    group_id = int(v["group_id"])
                    if group_id < 0:
                        raise ValueError("group_id должен быть положительным")
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Неверный group_id: {e}") from e

        return v


class OutputPresetCreate(OutputPresetBase):
    """Схема для создания пресета."""

    credential_id: int = Field(..., description="ID credentials")


class OutputPresetUpdate(BaseModel):
    """Схема для обновления пресета."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    credential_id: int | None = None
    preset_metadata: dict[str, Any] | None = None
    is_active: bool | None = None


class OutputPresetResponse(OutputPresetBase):
    """Схема ответа для пресета."""

    id: int
    user_id: int
    credential_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

