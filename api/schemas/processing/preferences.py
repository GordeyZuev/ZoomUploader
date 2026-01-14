"""Processing preferences schemas"""

from pydantic import BaseModel, Field


class ProcessingPreferences(BaseModel):
    """Настройки обработки записи."""

    enable_transcription: bool = Field(True, description="Включить транскрибацию")
    enable_subtitles: bool = Field(True, description="Включить генерацию субтитров")
    enable_topics: bool = Field(True, description="Включить извлечение тем")
    granularity: str = Field("long", description="Уровень детализации извлечения тем (short/long)")
    transcription_model: str = Field("fireworks", description="Модель для транскрибации")
    topic_model: str = Field("deepseek", description="Модель для извлечения тем")

    class Config:
        json_schema_extra = {
            "example": {
                "enable_transcription": True,
                "enable_subtitles": True,
                "enable_topics": True,
                "granularity": "long",
                "transcription_model": "fireworks",
                "topic_model": "deepseek",
            }
        }
