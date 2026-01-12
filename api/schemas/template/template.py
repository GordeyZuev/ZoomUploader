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
    processing_config: dict[str, Any] | None = Field(
        None,
        description="Processing settings (transcribe, extract_topics, etc)"
    )
    metadata_config: dict[str, Any] | None = Field(
        None,
        description="Content-specific metadata (title_template, playlist_id, thumbnail_path, tags). "
        "Can also override preset defaults (e.g., privacy, topics_display format) via deep merge."
    )
    output_config: dict[str, Any] | None = Field(
        None,
        description="Output configuration (preset_ids list)"
    )

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
        valid_rules = ["exact_matches", "keywords", "patterns", "source_ids"]
        has_rule = any(rule in v for rule in valid_rules)

        if not has_rule:
            raise ValueError(f"Должно быть хотя бы одно правило из: {', '.join(valid_rules)}")

        # Валидируем patterns (regex)
        if "patterns" in v:
            if not isinstance(v["patterns"], list):
                raise ValueError("patterns должен быть списком")
            for pattern in v["patterns"]:
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise ValueError(f"Неверный regex в patterns: {e}") from e

        # Валидируем exact_matches
        if "exact_matches" in v and not isinstance(v["exact_matches"], list):
            raise ValueError("exact_matches должен быть списком")

        # Валидируем keywords
        if "keywords" in v and not isinstance(v["keywords"], list):
            raise ValueError("keywords должен быть списком")

        # Валидируем source_ids
        if "source_ids" in v:
            if not isinstance(v["source_ids"], list):
                raise ValueError("source_ids должен быть списком")
            if not all(isinstance(sid, int) for sid in v["source_ids"]):
                raise ValueError("source_ids должен содержать целые числа")

        return v

    @field_validator("output_config")
    @classmethod
    def validate_output_config(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Валидация конфигурации выгрузки."""
        if v is None:
            return v

        # Проверяем наличие preset_ids (должен быть list of integers)
        if "preset_ids" in v:
            if not isinstance(v["preset_ids"], list):
                raise ValueError("preset_ids должен быть списком целых чисел")
            if not v["preset_ids"]:
                raise ValueError("preset_ids не может быть пустым списком")
            if not all(isinstance(pid, int) and pid > 0 for pid in v["preset_ids"]):
                raise ValueError("preset_ids должен содержать только положительные целые числа")

        return v


class RecordingTemplateCreate(RecordingTemplateBase):
    """Схема для создания шаблона."""

    is_draft: bool = Field(False, description="Черновик")


class RecordingTemplateUpdate(BaseModel):
    """Схема для обновления шаблона."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    matching_rules: dict[str, Any] | None = None
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


class RecordingTemplateListResponse(BaseModel):
    """Схема для списка шаблонов."""

    id: int
    name: str
    description: str | None
    is_draft: bool
    is_active: bool
    used_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

