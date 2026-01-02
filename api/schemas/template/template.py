"""Схемы для шаблонов записей."""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RecordingTemplateBase(BaseModel):
    """Базовая схема для шаблона."""

    name: str = Field(..., min_length=1, max_length=255, description="Название шаблона")
    description: str | None = Field(None, max_length=1000, description="Описание шаблона")
    matching_rules: dict[str, Any] | None = Field(None, description="Правила сопоставления")
    priority: int = Field(0, ge=0, le=1000, description="Приоритет (чем выше, тем раньше)")
    processing_config: dict[str, Any] | None = Field(None, description="Настройки обработки")
    metadata_config: dict[str, Any] | None = Field(None, description="Метаданные для публикации")
    output_config: dict[str, Any] | None = Field(None, description="Конфигурация выгрузки")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Валидация названия шаблона."""
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("matching_rules")
    @classmethod
    def validate_matching_rules(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Валидация правил сопоставления."""
        if v is None:
            return v

        # Проверяем наличие хотя бы одного правила
        valid_rules = ["name_pattern", "source_type", "source_id", "tag_pattern"]
        has_rule = any(rule in v for rule in valid_rules)

        if not has_rule:
            raise ValueError(f"Должно быть хотя бы одно правило из: {', '.join(valid_rules)}")

        # Валидируем регулярные выражения
        if "name_pattern" in v:
            try:
                re.compile(v["name_pattern"])
            except re.error as e:
                raise ValueError(f"Неверный regex в name_pattern: {e}") from e

        if "tag_pattern" in v:
            try:
                re.compile(v["tag_pattern"])
            except re.error as e:
                raise ValueError(f"Неверный regex в tag_pattern: {e}") from e

        # Валидируем source_type
        if "source_type" in v and v["source_type"] not in ["ZOOM", "YANDEX_DISK", "LOCAL", "GOOGLE_DRIVE"]:
            raise ValueError("source_type должен быть: ZOOM, YANDEX_DISK, LOCAL или GOOGLE_DRIVE")

        return v

    @field_validator("metadata_config")
    @classmethod
    def validate_metadata_config(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Валидация конфигурации метаданных."""
        if v is None:
            return v

        # Проверяем использование переменных (они должны быть в фигурных скобках)
        for key, value in v.items():
            if isinstance(value, str) and "{" in value:
                # Проверяем, что все переменные корректно закрыты
                if value.count("{") != value.count("}"):
                    raise ValueError(f"Некорректные переменные в поле {key}: {value}")

        return v

    @field_validator("output_config")
    @classmethod
    def validate_output_config(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Валидация конфигурации выгрузки."""
        if v is None:
            return v

        # Проверяем наличие preset_ids
        if "preset_ids" in v:
            if not isinstance(v["preset_ids"], list):
                raise ValueError("preset_ids должен быть списком")
            if not v["preset_ids"]:
                raise ValueError("preset_ids не может быть пустым списком")
            if not all(isinstance(pid, int) and pid > 0 for pid in v["preset_ids"]):
                raise ValueError("preset_ids должен содержать положительные целые числа")

        return v


class RecordingTemplateCreate(RecordingTemplateBase):
    """Схема для создания шаблона."""

    is_draft: bool = Field(False, description="Черновик")


class RecordingTemplateUpdate(BaseModel):
    """Схема для обновления шаблона."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    matching_rules: dict[str, Any] | None = None
    priority: int | None = Field(None, ge=0)
    processing_config: dict[str, Any] | None = None
    metadata_config: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    is_draft: bool | None = None
    is_active: bool | None = None


class RecordingTemplateResponse(RecordingTemplateBase):
    """Схема ответа для шаблона."""

    id: int
    user_id: int
    is_draft: bool
    is_active: bool
    used_count: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

