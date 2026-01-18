"""Typed schemas for preset_metadata"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import BASE_MODEL_CONFIG

# ============================================================================
# Общие схемы для всех платформ
# ============================================================================


class TopicsDisplayFormat(str, Enum):
    """Формат отображения тем."""

    NUMBERED_LIST = "numbered_list"  # "1. Тема\n2. Тема"
    BULLET_LIST = "bullet_list"  # "• Тема\n• Тема"
    DASH_LIST = "dash_list"  # "- Тема\n- Тема"
    COMMA_SEPARATED = "comma_separated"  # "Тема 1, Тема 2, Тема 3"
    INLINE = "inline"  # "Тема 1 | Тема 2 | Тема 3"


class TopicsDisplayConfig(BaseModel):
    """Конфигурация отображения тем в description."""

    model_config = BASE_MODEL_CONFIG

    enabled: bool = Field(True, description="Включить отображение тем")
    format: TopicsDisplayFormat = Field(TopicsDisplayFormat.NUMBERED_LIST, description="Формат списка")
    max_count: int | None = Field(None, ge=1, le=100, description="Максимальное количество тем (None = все)")
    min_length: int | None = Field(None, ge=0, le=500, description="Минимальная длина темы в символах")
    max_length: int | None = Field(None, ge=10, le=1000, description="Максимальная длина темы в символах")
    prefix: str | None = Field(None, max_length=200, description="Префикс перед списком тем")
    separator: str = Field("\n", max_length=10, description="Разделитель между темами")
    show_timestamps: bool = Field(False, description="Показывать временные метки для тем")

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            return v if v else None
        return v


# ============================================================================
# YouTube-специфичные схемы
# ============================================================================


class YouTubePrivacy(str, Enum):
    """YouTube privacy статусы."""

    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"


class YouTubeLicense(str, Enum):
    """YouTube лицензии."""

    YOUTUBE = "youtube"
    CREATIVE_COMMON = "creativeCommon"


class YouTubePresetMetadata(BaseModel):
    """YouTube preset metadata (platform defaults)."""

    model_config = BASE_MODEL_CONFIG

    # Content templates (added for preset-level control)
    title_template: str | None = Field(
        None,
        max_length=500,
        description="Шаблон заголовка с переменными (напр. '{display_name} | {themes}')",
    )
    description_template: str | None = Field(
        None,
        max_length=5000,
        description="Шаблон описания с переменными (напр. '{summary}\\n\\n{topics}')",
    )

    # Privacy settings
    privacy: YouTubePrivacy = Field(YouTubePrivacy.UNLISTED, description="Статус приватности")
    made_for_kids: bool = Field(False, description="Контент для детей (COPPA)")
    embeddable: bool = Field(True, description="Разрешить встраивание на других сайтах")

    # Platform defaults
    category_id: str = Field("27", description="Категория YouTube (27 = Education)")
    license: YouTubeLicense = Field(YouTubeLicense.YOUTUBE, description="Тип лицензии")
    default_language: str | None = Field(None, description="Язык по умолчанию", examples=["ru", "en"])

    # Platform organization
    playlist_id: str | None = Field(None, description="ID плейлиста YouTube для автозагрузки видео")
    tags: list[str] | None = Field(None, max_length=500, description="Теги видео (макс 500)")
    thumbnail_path: str | None = Field(None, description="Путь к файлу thumbnail (обложка видео)")

    # Scheduling
    publish_at: str | None = Field(None, description="ISO 8601 дата/время публикации (для отложенной публикации)")

    # Topics display
    topics_display: TopicsDisplayConfig | None = Field(None, description="Настройки отображения тем в description")

    # Optional comments/ratings
    disable_comments: bool = Field(False, description="Отключить комментарии")
    rating_disabled: bool = Field(False, description="Отключить оценки like/dislike")

    # Notifications
    notify_subscribers: bool = Field(True, description="Уведомить подписчиков о публикации")

    @field_validator("category_id")
    @classmethod
    def validate_category_id(cls, v: str) -> str:
        # YouTube category IDs - базовая валидация
        try:
            cat_int = int(v)
            if cat_int < 1:
                raise ValueError("category_id должен быть положительным")
        except ValueError:
            raise ValueError("category_id должен быть числом")
        return v


# ============================================================================
# VK-специфичные схемы
# ============================================================================


class VKPrivacyLevel(int, Enum):
    """VK уровни приватности."""

    ALL = 0  # Все пользователи
    FRIENDS = 1  # Только друзья
    FRIENDS_OF_FRIENDS = 2  # Друзья и друзья друзей
    ONLY_ME = 3  # Только я


class VKPresetMetadata(BaseModel):
    """VK preset metadata (platform defaults)."""

    model_config = BASE_MODEL_CONFIG

    # Content templates (added for preset-level control)
    title_template: str | None = Field(
        None,
        max_length=500,
        description="Шаблон заголовка с переменными (напр. '{display_name}')",
    )
    description_template: str | None = Field(
        None,
        max_length=5000,
        description="Шаблон описания с переменными (напр. '{summary}\\n\\n{topics}')",
    )

    # Privacy settings
    privacy_view: VKPrivacyLevel = Field(
        VKPrivacyLevel.ALL,
        description="Кто может смотреть видео (0=все, 1=друзья, 2=друзья друзей, 3=только я)",
    )
    privacy_comment: VKPrivacyLevel = Field(
        VKPrivacyLevel.ALL,
        description="Кто может комментировать (0=все, 1=друзья, 2=друзья друзей, 3=только я)",
    )

    # Group settings (optional - может быть в template)
    group_id: int | None = Field(None, gt=0, description="ID группы VK (можно задать в template metadata_config)")
    album_id: str | None = Field(None, description="ID альбома VK")
    thumbnail_path: str | None = Field(None, description="Путь к файлу thumbnail (обложка видео)")

    # Topics display
    topics_display: TopicsDisplayConfig | None = Field(None, description="Настройки отображения тем в description")

    # Optional settings
    disable_comments: bool = Field(False, description="Полностью отключить комментарии")
    repeat: bool = Field(False, description="Зациклить воспроизведение")
    compression: bool = Field(False, description="Сжатие видео на стороне VK")
    wallpost: bool = Field(False, description="Опубликовать запись на стене при загрузке")

    @field_validator("group_id")
    @classmethod
    def validate_group_id(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("group_id должен быть положительным")
        return v


# ============================================================================
# Unified Preset Metadata
# ============================================================================


PresetMetadata = YouTubePresetMetadata | VKPresetMetadata
