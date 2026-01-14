"""Типизированные схемы для input source config."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import BASE_MODEL_CONFIG
from api.schemas.common.validators import validate_regex_pattern

# ============================================================================
# Zoom Source Config
# ============================================================================


class ZoomSourceConfig(BaseModel):
    """Конфигурация Zoom источника."""

    model_config = BASE_MODEL_CONFIG

    user_id: str | None = Field(None, description="Zoom user ID для фильтрации (опционально)")
    include_trash: bool = Field(False, description="Включить удаленные записи")
    recording_type: Literal["cloud", "all"] = Field("cloud", description="Тип записей: cloud или all")


# ============================================================================
# Google Drive Source Config
# ============================================================================


class GoogleDriveSourceConfig(BaseModel):
    """Конфигурация Google Drive источника."""

    model_config = BASE_MODEL_CONFIG

    folder_id: str = Field(..., description="ID папки на Google Drive")
    recursive: bool = Field(True, description="Рекурсивный поиск в подпапках")
    file_pattern: str | None = Field(
        None,
        description="Regex паттерн для фильтрации файлов",
        examples=[".*\\.mp4$", "Лекция.*\\.mp4"],
    )

    @field_validator("file_pattern")
    @classmethod
    def validate_pattern(cls, v: str | None) -> str | None:
        return validate_regex_pattern(v, field_name="file_pattern")


# ============================================================================
# Yandex Disk Source Config
# ============================================================================


class YandexDiskSourceConfig(BaseModel):
    """Конфигурация Yandex Disk источника."""

    model_config = BASE_MODEL_CONFIG

    folder_path: str = Field(..., description="Путь к папке на Яндекс.Диске", examples=["/Видео/Лекции"])
    recursive: bool = Field(True, description="Рекурсивный поиск в подпапках")
    file_pattern: str | None = Field(None, description="Regex паттерн для фильтрации файлов")

    @field_validator("file_pattern")
    @classmethod
    def validate_pattern(cls, v: str | None) -> str | None:
        return validate_regex_pattern(v, field_name="file_pattern")


# ============================================================================
# Local File Source Config
# ============================================================================


class LocalFileSourceConfig(BaseModel):
    """Конфигурация локального источника файлов."""

    model_config = BASE_MODEL_CONFIG


# ============================================================================
# Unified Source Config
# ============================================================================

SourceConfig = ZoomSourceConfig | GoogleDriveSourceConfig | YandexDiskSourceConfig | LocalFileSourceConfig
