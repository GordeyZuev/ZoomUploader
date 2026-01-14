"""Схемы для источников данных (полностью типизированные)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from api.schemas.common import BASE_MODEL_CONFIG, ORM_MODEL_CONFIG

from .source_config import GoogleDriveSourceConfig, LocalFileSourceConfig, YandexDiskSourceConfig, ZoomSourceConfig

# ============================================================================
# Input Source Schemas (Fully Typed)
# ============================================================================


class InputSourceBase(BaseModel):
    """Базовая схема для источника с полной типизацией."""

    model_config = BASE_MODEL_CONFIG

    name: str = Field(..., min_length=3, max_length=255, description="Название источника")
    description: str | None = Field(None, max_length=1000, description="Описание источника")

    config: ZoomSourceConfig | GoogleDriveSourceConfig | YandexDiskSourceConfig | LocalFileSourceConfig | None = Field(
        None,
        description="Platform-specific config",
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Очистка названия от пробелов."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Название не может быть пустым")
        return v


class InputSourceCreate(BaseModel):
    """Схема для создания источника."""

    model_config = BASE_MODEL_CONFIG

    name: str = Field(..., min_length=3, max_length=255, description="Название источника")
    description: str | None = Field(None, max_length=1000, description="Описание источника")
    platform: Literal["ZOOM", "GOOGLE_DRIVE", "YANDEX_DISK", "LOCAL"] = Field(..., description="Платформа")
    credential_id: int | None = Field(None, gt=0, description="ID credentials (обязательно для всех кроме LOCAL)")

    config: ZoomSourceConfig | GoogleDriveSourceConfig | YandexDiskSourceConfig | LocalFileSourceConfig | None = Field(
        None,
        description="Platform-specific config",
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Очистка названия от пробелов."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Название не может быть пустым")
        return v

    @model_validator(mode="after")
    def validate_source(self) -> "InputSourceCreate":
        """Кросс-валидация source."""
        # Все кроме LOCAL требуют credential_id
        if self.platform != "LOCAL" and not self.credential_id:
            raise ValueError(f"Platform {self.platform} требует credential_id")

        # LOCAL не должен иметь credential_id
        if self.platform == "LOCAL" and self.credential_id:
            raise ValueError("LOCAL source не должен иметь credential_id")

        return self


class InputSourceUpdate(BaseModel):
    """Схема для обновления источника (полностью типизированная)."""

    name: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, max_length=1000)
    credential_id: int | None = Field(None, gt=0)
    config: ZoomSourceConfig | GoogleDriveSourceConfig | YandexDiskSourceConfig | LocalFileSourceConfig | None = None
    is_active: bool | None = None


class InputSourceResponse(BaseModel):
    """Схема ответа для источника."""

    model_config = ORM_MODEL_CONFIG

    id: int
    user_id: int
    name: str
    description: str | None
    source_type: str
    credential_id: int | None
    config: ZoomSourceConfig | GoogleDriveSourceConfig | YandexDiskSourceConfig | LocalFileSourceConfig | None
    is_active: bool
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Batch Sync Schemas
# ============================================================================


class BulkSyncRequest(BaseModel):
    """Схема для bulk sync запроса."""

    model_config = BASE_MODEL_CONFIG

    source_ids: list[int] = Field(..., min_length=1, max_length=50, description="Список ID источников для синхронизации")
    from_date: str = Field("2024-01-01", description="Дата начала в формате YYYY-MM-DD")
    to_date: str | None = Field(None, description="Дата окончания в формате YYYY-MM-DD (опционально)")


# Alias for backward compatibility
BatchSyncRequest = BulkSyncRequest


class SourceSyncResult(BaseModel):
    """Результат синхронизации одного источника."""

    model_config = BASE_MODEL_CONFIG

    source_id: int
    source_name: str | None = None
    status: str
    recordings_found: int | None = None
    recordings_saved: int | None = None
    recordings_updated: int | None = None
    error: str | None = None


class BatchSyncResponse(BaseModel):
    """Схема ответа для batch sync."""

    model_config = BASE_MODEL_CONFIG

    message: str
    total_sources: int
    successful: int
    failed: int
    results: list[SourceSyncResult]
