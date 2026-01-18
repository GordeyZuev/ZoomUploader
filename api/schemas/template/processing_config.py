"""Typed schemas for processing_config"""

from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.common import BASE_MODEL_CONFIG

# ============================================================================
# Processing Config (плоская структура как в реальных данных)
# ============================================================================


class TemplateProcessingConfig(BaseModel):
    """
    Processing configuration для template.

    Все настройки обработки в одном объекте transcription (историческая структура).
    """

    model_config = BASE_MODEL_CONFIG

    transcription: "TranscriptionProcessingConfig" = Field(
        ...,
        description="Настройки обработки: транскрибация, топики, субтитры",
    )


class TranscriptionProcessingConfig(BaseModel):
    """
    Объединенные настройки обработки (плоская структура).

    Содержит настройки для:
    - Транскрибации (enable_transcription, prompt, language)
    - Извлечения тем (enable_topics, granularity)
    - Субтитров (enable_subtitles)
    """

    model_config = BASE_MODEL_CONFIG

    # Transcription
    enable_transcription: bool = Field(True, description="Включить транскрибацию")
    prompt: str | None = Field(None, description="Промпт для улучшения качества транскрибации")
    language: str | None = Field(None, description="Язык аудио (ru, en, ...)", examples=["ru", "en"])

    # Topics
    enable_topics: bool = Field(True, description="Включить извлечение тем")
    granularity: Literal["short", "long"] = Field("long", description="Детализация тем: short или long")

    # Subtitles
    enable_subtitles: bool = Field(True, description="Включить генерацию субтитров")


# Обновляем forward reference
TemplateProcessingConfig.model_rebuild()
