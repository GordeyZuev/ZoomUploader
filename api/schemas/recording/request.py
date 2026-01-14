"""Схемы запросов для recordings."""

from datetime import date

from pydantic import BaseModel, Field, model_validator

from api.schemas.processing.preferences import ProcessingPreferences
from api.schemas.recording.filters import RecordingFilters
from api.schemas.validators import DateRangeMixin


class ProcessRecordingRequest(BaseModel):
    """Запрос на обработку записи."""

    transcription_model: str = Field("fireworks", description="Модель для транскрибации")
    granularity: str = Field("long", description="Уровень детализации извлечения тем (short/long)")
    topic_model: str = Field("deepseek", description="Модель для извлечения тем")
    platforms: list[str] = Field(default_factory=list, description="Платформы для загрузки")
    no_transcription: bool = Field(False, description="Пропустить транскрибацию")

    class Config:
        json_schema_extra = {
            "example": {
                "transcription_model": "fireworks",
                "granularity": "long",
                "topic_model": "deepseek",
                "platforms": ["youtube"],
                "no_transcription": False,
            }
        }


class DateRangeRequest(BaseModel, DateRangeMixin):
    """Базовый запрос с диапазоном дат."""

    from_date: date | None = Field(
        None,
        description="Дата начала. Форматы: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY",
        examples=["2024-12-01", "01/12/2024", "01-12-2024"],
    )
    to_date: date | None = Field(
        None,
        description="Дата окончания (включительно). Если не указана — до текущего момента",
        examples=["2025-01-01", "01/01/2025"],
    )
    last_days: int | None = Field(
        None,
        ge=0,
        le=365,
        description="Последние N дней. Перекрывает from_date/to_date. 0 = только сегодня",
        examples=[7, 14, 30],
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {"last_days": 10},
                {"from_date": "2024-12-01", "to_date": "2025-01-01"},
                {"from_date": "01/12/2024"},
            ]
        }


class BatchProcessRequest(DateRangeRequest):
    """Запрос на пакетную обработку."""

    select_all: bool = Field(False, description="Обработать все найденные записи")
    recording_ids: list[int] | None = Field(
        None, description="Список конкретных ID записей. Если указан — игнорирует даты"
    )
    platforms: list[str] = Field(default_factory=list, description="Платформы для загрузки (youtube, vk)")
    no_transcription: bool = Field(False, description="Пропустить транскрибацию")

    class Config:
        json_schema_extra = {
            "examples": [
                {"last_days": 7, "platforms": ["youtube"], "no_transcription": False},
                {"recording_ids": [1, 2, 3], "platforms": ["youtube", "vk"]},
            ]
        }


class GenerateSubtitlesRequest(BaseModel):
    """Запрос на генерацию субтитров."""

    recording_ids: list[int] = Field(..., description="ID записей", min_length=1)
    formats: list[str] = Field(default=["srt", "vtt"], description="Форматы субтитров")

    class Config:
        json_schema_extra = {"example": {"recording_ids": [1, 2, 3], "formats": ["srt", "vtt"]}}


class UploadRecordingsRequest(BaseModel):
    """Запрос на загрузку записей."""

    recording_ids: list[int] = Field(..., description="ID записей", min_length=1)
    platforms: list[str] = Field(..., description="Платформы для загрузки (youtube, vk)", min_length=1)
    upload_captions: bool | None = Field(None, description="Загружать субтитры. По умолчанию из конфига")

    class Config:
        json_schema_extra = {"example": {"recording_ids": [1, 2, 3], "platforms": ["youtube"], "upload_captions": True}}


class UpdateRecordingRequest(BaseModel):
    """Запрос на обновление записи."""

    processing_preferences: ProcessingPreferences | None = Field(None, description="Настройки обработки")

    class Config:
        json_schema_extra = {
            "example": {
                "processing_preferences": {
                    "enable_transcription": True,
                    "enable_subtitles": True,
                    "enable_topics": True,
                }
            }
        }


# ============================================================================
# Bulk Operations - Base Classes
# ============================================================================


class BulkOperationRequest(BaseModel):
    """
    Базовая схема для всех bulk операций.

    Поддерживает два режима:
    1. Явный список recording_ids
    2. Автоматическая выборка по filters

    Только один из режимов может быть использован одновременно.
    """

    recording_ids: list[int] | None = Field(
        None,
        description="Явный список ID записей для обработки",
        min_length=1
    )
    filters: RecordingFilters | None = Field(
        None,
        description="Фильтры для автоматической выборки записей"
    )
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="Максимальное количество записей при использовании filters"
    )

    @model_validator(mode='after')
    def validate_input(self):
        """Валидация: должен быть указан либо recording_ids, либо filters."""
        if not self.recording_ids and not self.filters:
            raise ValueError("Укажите recording_ids или filters")
        if self.recording_ids and self.filters:
            raise ValueError("Укажите только recording_ids ИЛИ filters, не оба параметра")
        return self

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "recording_ids": [1, 2, 3, 4, 5]
                },
                {
                    "filters": {
                        "template_id": 5,
                        "status": ["INITIALIZED"],
                        "is_mapped": True
                    },
                    "limit": 50
                }
            ]
        }


# ============================================================================
# Bulk Operations - Specific Request Schemas
# ============================================================================


class BulkDownloadRequest(BulkOperationRequest):
    """Bulk скачивание записей из Zoom."""

    force: bool = Field(False, description="Пересохранить если уже скачано")
    allow_skipped: bool = Field(False, description="Разрешить загрузку SKIPPED записей")

    class Config:
        json_schema_extra = {
            "example": {
                "filters": {
                    "source_id": 10,
                    "status": ["PENDING"]
                },
                "force": False,
                "allow_skipped": False
            }
        }


class BulkTrimRequest(BulkOperationRequest):
    """Bulk обработка видео (FFmpeg - удаление тишины)."""

    silence_threshold: float = Field(-40.0, description="Порог тишины в dB")
    min_silence_duration: float = Field(2.0, description="Минимальная длительность тишины в секундах")
    padding_before: float = Field(5.0, description="Отступ перед речью в секундах")
    padding_after: float = Field(5.0, description="Отступ после речи в секундах")

    class Config:
        json_schema_extra = {
            "example": {
                "recording_ids": [1, 2, 3],
                "silence_threshold": -35.0,
                "min_silence_duration": 3.0
            }
        }


class BulkTranscribeRequest(BulkOperationRequest):
    """Bulk транскрибация записей."""

    use_batch_api: bool = Field(
        False,
        description="Использовать Fireworks Batch API (экономия ~50%, но дольше)"
    )
    poll_interval: float = Field(10.0, description="Интервал polling для Batch API (секунды)")
    max_wait_time: float = Field(3600.0, description="Максимальное время ожидания Batch API (секунды)")

    class Config:
        json_schema_extra = {
            "example": {
                "filters": {
                    "template_id": 5,
                    "status": ["DOWNLOADED", "PROCESSED"]
                },
                "use_batch_api": True,
                "limit": 100
            }
        }


class BulkTopicsRequest(BulkOperationRequest):
    """Bulk извлечение тем из транскрибаций."""

    granularity: str = Field("long", description="Режим извлечения ('short' - крупные темы | 'long' - детальные)")
    version_id: str | None = Field(None, description="ID версии (если не указан, генерируется автоматически)")

    class Config:
        json_schema_extra = {
            "example": {
                "filters": {
                    "status": ["TRANSCRIBED"],
                    "template_id": 5
                },
                "granularity": "long",
                "limit": 50
            }
        }


class BulkSubtitlesRequest(BulkOperationRequest):
    """Bulk генерация субтитров."""

    formats: list[str] = Field(
        default=["srt", "vtt"],
        description="Форматы субтитров для генерации"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "recording_ids": [1, 2, 3],
                "formats": ["srt", "vtt"]
            }
        }


class BulkUploadRequest(BulkOperationRequest):
    """Bulk загрузка записей на платформы."""

    platforms: list[str] | None = Field(
        None,
        description="Платформы для загрузки (youtube, vk). Если None - из preset"
    )
    preset_id: int | None = Field(None, description="Override preset ID для всех записей")

    class Config:
        json_schema_extra = {
            "example": {
                "filters": {
                    "status": ["TOPICS_EXTRACTED"],
                    "is_mapped": True
                },
                "platforms": ["youtube", "vk"],
                "limit": 30
            }
        }


class BulkProcessRequest(BulkOperationRequest):
    """Bulk полный пайплайн обработки (download → trim → transcribe → topics → upload)."""

    processing_config: dict | None = Field(None, description="Override processing config для всех записей")
    metadata_config: dict | None = Field(None, description="Override metadata config для всех записей")
    output_config: dict | None = Field(None, description="Override output config для всех записей")

    class Config:
        json_schema_extra = {
            "example": {
                "filters": {
                    "template_id": 5,
                    "status": ["INITIALIZED", "FAILED"],
                    "is_mapped": True
                },
                "output_config": {
                    "auto_upload": True,
                    "platforms": ["youtube"]
                },
                "limit": 50
            }
        }
