"""Typed schemas for output_config"""

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import BASE_MODEL_CONFIG

# ============================================================================
# Output Config
# ============================================================================


class TemplateOutputConfig(BaseModel):
    """
    Output configuration для template.

    Определяет:
    - preset_ids: список пресетов для автозагрузки
    - auto_upload: автоматическая загрузка после обработки
    - upload_captions: загружать ли субтитры вместе с видео
    """

    model_config = BASE_MODEL_CONFIG

    preset_ids: list[int] = Field(
        ...,
        description="Список ID пресетов для автозагрузки",
        min_length=1,
        examples=[[1], [1, 2, 3]],
    )

    auto_upload: bool = Field(
        False,
        description="Автоматическая загрузка после обработки (если False - только по явному запросу)",
    )

    upload_captions: bool = Field(
        True,
        description="Загружать субтитры вместе с видео (если доступно на платформе)",
    )

    @field_validator("preset_ids")
    @classmethod
    def validate_preset_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("preset_ids не может быть пустым")
        if len(v) > 10:
            raise ValueError("Максимум 10 пресетов на template")
        if any(pid <= 0 for pid in v):
            raise ValueError("preset_ids должны быть положительными числами")
        # Проверка уникальности
        if len(v) != len(set(v)):
            raise ValueError("preset_ids не должны дублироваться")
        return v

