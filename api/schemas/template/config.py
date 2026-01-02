"""Схемы для базовых конфигураций."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class BaseConfigBase(BaseModel):
    """Базовая схема для конфигурации."""

    name: str = Field(..., min_length=1, max_length=255, description="Название конфигурации")
    description: str | None = Field(None, max_length=1000, description="Описание конфигурации")
    config_type: str | None = Field(None, description="Тип конфигурации (processing, transcription, etc)")
    config_data: dict[str, Any] = Field(..., description="Данные конфигурации")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Валидация названия конфигурации."""
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("config_data")
    @classmethod
    def validate_config_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Валидация данных конфигурации."""
        if not v:
            raise ValueError("config_data не может быть пустым")

        # Проверяем типы известных полей (базовая валидация)
        if "max_file_size_mb" in v:
            try:
                size = float(v["max_file_size_mb"])
                if size <= 0:
                    raise ValueError("max_file_size_mb должен быть положительным")
            except (ValueError, TypeError) as e:
                raise ValueError(f"Неверный max_file_size_mb: {e}") from e

        if "allowed_formats" in v and not isinstance(v["allowed_formats"], list):
            raise ValueError("allowed_formats должен быть списком")

        return v

    @model_validator(mode="after")
    def validate_config_by_type(self) -> "BaseConfigBase":
        """Валидация config_data по config_type."""
        if self.config_type:
            try:
                from api.schemas.config_types import validate_config_by_type

                # Валидируем через типизированную схему
                validate_config_by_type(self.config_type, self.config_data)
            except Exception as e:
                raise ValueError(f"Invalid config_data for type '{self.config_type}': {e}") from e
        return self


class BaseConfigCreate(BaseConfigBase):
    """Схема для создания конфигурации."""

    is_global: bool = Field(False, description="Глобальная конфигурация (только для admin)")


class BaseConfigUpdate(BaseModel):
    """Схема для обновления конфигурации."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    config_data: dict[str, Any] | None = None
    is_active: bool | None = None


class BaseConfigResponse(BaseConfigBase):
    """Схема ответа для конфигурации."""

    id: int
    user_id: int | None
    is_active: bool
    is_global: bool = Field(False, description="Глобальная конфигурация")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_model(cls, model) -> "BaseConfigResponse":
        """Создать из ORM модели."""
        return cls(
            id=model.id,
            name=model.name,
            description=model.description,
            config_type=model.config_type,
            config_data=model.config_data,
            user_id=model.user_id,
            is_active=model.is_active,
            is_global=(model.user_id is None),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    class Config:
        from_attributes = True

