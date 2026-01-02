"""Схемы запросов для recordings."""

from datetime import date

from pydantic import BaseModel, Field

from api.schemas.processing.preferences import ProcessingPreferences
from api.schemas.validators import DateRangeMixin


class ProcessRecordingRequest(BaseModel):
    """Запрос на обработку записи."""

    transcription_model: str = Field("fireworks", description="Модель для транскрибации")
    topic_mode: str = Field("long", description="Режим извлечения тем (short/long)")
    topic_model: str = Field("deepseek", description="Модель для извлечения тем")
    platforms: list[str] = Field(default_factory=list, description="Платформы для загрузки")
    no_transcription: bool = Field(False, description="Пропустить транскрибацию")

    class Config:
        json_schema_extra = {
            "example": {
                "transcription_model": "fireworks",
                "topic_mode": "long",
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
