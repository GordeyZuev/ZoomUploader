"""Типизированные схемы для metadata_config (по реальной структуре)."""

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import BASE_MODEL_CONFIG

from .preset_metadata import TopicsDisplayConfig

# ============================================================================
# Platform-specific metadata
# ============================================================================


class VKMetadataConfig(BaseModel):
    """VK-специфичные настройки metadata."""

    model_config = BASE_MODEL_CONFIG

    album_id: str | None = Field(None, description="ID альбома VK")
    thumbnail_path: str | None = Field(None, description="Путь к thumbnail для VK")


class YouTubeMetadataConfig(BaseModel):
    """YouTube-специфичные настройки metadata."""

    model_config = BASE_MODEL_CONFIG

    privacy: str | None = Field(None, description="Privacy status (public, unlisted, private)")
    playlist_id: str | None = Field(None, description="ID плейлиста YouTube")
    thumbnail_path: str | None = Field(None, description="Путь к thumbnail для YouTube")


# ============================================================================
# Template Metadata Config (реальная структура с платформенными блоками)
# ============================================================================


class TemplateMetadataConfig(BaseModel):
    """
    Content-specific metadata для Recording Template.

    Структура:
    - vk: VK-специфичные настройки (album_id, thumbnail_path)
    - youtube: YouTube-специфичные настройки (privacy, playlist_id, thumbnail_path)
    - title_template: общий шаблон заголовка
    - topics_display: общие настройки отображения тем

    Переменные в templates:
    - {display_name}, {themes}, {topic}, {topics}, {topics_list}
    - {summary}, {record_time}, {publish_time}, {date}, {duration}
    """

    model_config = BASE_MODEL_CONFIG

    # Платформо-специфичные блоки
    vk: VKMetadataConfig | None = Field(None, description="VK-специфичные настройки")
    youtube: YouTubeMetadataConfig | None = Field(None, description="YouTube-специфичные настройки")

    # Общие настройки (для всех платформ)
    title_template: str | None = Field(
        None,
        max_length=500,
        description="Шаблон заголовка с переменными",
        examples=[
            "Курс ИИ | {themes} ({record_time:DD.MM.YY})",
            "{display_name} - {date}",
            "Обучение с подкреплением | {themes}",
        ],
    )

    topics_display: TopicsDisplayConfig | None = Field(
        None,
        description="Настройки отображения тем в description (для всех платформ)",
    )

    @field_validator("title_template")
    @classmethod
    def validate_title_template(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                return None
            # Проверка что есть хоть одна переменная
            valid_vars = ["{display_name}", "{themes}", "{topic}", "{date}", "{record_time}", "{duration}"]
            if not any(var in v for var in valid_vars):
                raise ValueError(f"title_template должен содержать хоть одну переменную из: {', '.join(valid_vars)}")
        return v

