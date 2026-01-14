"""Unified application configuration"""

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from logger import get_logger

logger = get_logger()


class PlatformConfig(BaseSettings, ABC):
    """Base platform configuration"""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    enabled: bool = Field(
        default=True,
        description="Включена ли платформа",
    )

    @abstractmethod
    def validate(self) -> bool:
        """Валидация конфигурации"""
        pass


class YouTubeConfig(PlatformConfig):
    """Конфигурация YouTube API"""

    client_secrets_file: str = Field(
        default="config/youtube_client_secrets.json",
        description="Путь к файлу с секретами клиента",
    )
    credentials_file: str = Field(
        default="config/youtube_credentials.json",
        description="Путь к файлу с credentials",
    )
    scopes: list[str] = Field(
        default_factory=lambda: [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
        description="Scopes для YouTube API",
    )
    default_privacy: Literal["private", "unlisted", "public"] = Field(
        default="unlisted",
        description="Приватность по умолчанию",
    )
    default_language: str = Field(
        default="ru",
        description="Язык по умолчанию",
    )

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        """Валидация scopes."""
        if not v:
            logger.warning("⚠️ Не указаны scopes для YouTube API")
        return v

    def validate(self) -> bool:
        """Валидация конфигурации YouTube"""
        if not self.enabled:
            return True

        if not os.path.exists(self.client_secrets_file):
            logger.warning(f"⚠️ Файл с секретами клиента не найден: {self.client_secrets_file}")

        if self.default_privacy not in ["private", "unlisted", "public"]:
            logger.error(f"❌ Неверный статус приватности: {self.default_privacy}")
            return False

        return True


class VKConfig(PlatformConfig):
    """Конфигурация VK API"""

    access_token: str = Field(
        default="",
        description="VK access token",
    )
    group_id: int | None = Field(
        default=None,
        description="ID группы VK",
    )
    album_id: int | None = Field(
        default=None,
        description="ID альбома VK (не используется, берется из правил маппинга)",
    )
    name: str = Field(
        default="",
        description="Название (не используется)",
    )
    description: str = Field(
        default="",
        description="Описание (не используется)",
    )
    privacy_view: Literal["0", "1", "2"] = Field(
        default="0",
        description="Настройки приватности просмотра",
    )
    privacy_comment: Literal["0", "1", "2"] = Field(
        default="1",
        description="Настройки приватности комментариев",
    )
    no_comments: bool = Field(
        default=False,
        description="Отключить комментарии",
    )
    repeat: bool = Field(
        default=False,
        description="Повторять загрузку",
    )

    def validate(self) -> bool:
        """Валидация конфигурации VK"""
        if not self.enabled:
            return True

        if not self.access_token:
            logger.warning("⚠️ VK access_token не указан")

        return True


class UploadSettings(BaseSettings):
    """Настройки загрузки"""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    max_file_size_mb: int = Field(
        default=5000,
        ge=1,
        description="Максимальный размер файла в МБ",
    )
    supported_formats: list[str] = Field(
        default_factory=lambda: ["mp4", "avi", "mov", "mkv", "webm", "m4v"],
        description="Поддерживаемые форматы файлов",
    )
    retry_attempts: int = Field(
        default=3,
        ge=1,
        description="Количество попыток при ошибке",
    )
    retry_delay: int = Field(
        default=5,
        ge=0,
        description="Задержка между попытками в секундах",
    )
    interactive_mode: bool = Field(
        default=True,
        description="Интерактивный режим",
    )
    default_privacy: Literal["private", "unlisted", "public"] = Field(
        default="unlisted",
        description="Приватность по умолчанию",
    )

    def validate_file(self, file_path: str) -> tuple[bool, str]:
        """Валидация файла перед загрузкой"""
        if not os.path.exists(file_path):
            return False, "Файл не существует"

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > self.max_file_size_mb:
            return (False, f"Файл слишком большой: {file_size_mb:.1f}MB > {self.max_file_size_mb}MB")

        file_ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        if file_ext not in self.supported_formats:
            return False, f"Неподдерживаемый формат: {file_ext}"

        return True, "OK"


class VideoTitleMapping(BaseSettings):
    """Конфигурация маппинга названий видео"""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    mapping_rules: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Правила маппинга названий",
    )
    default_rules: dict[str, Any] = Field(
        default_factory=dict,
        description="Правила по умолчанию",
    )
    date_format: str = Field(
        default="DD.MM.YYYY",
        description="Формат даты",
    )
    thumbnail_directory: str = Field(
        default="media/templates/thumbnails/",
        description="Директория для глобальных template миниатюр",
    )


class AppConfig(BaseSettings):
    """Главная конфигурация приложения"""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    video_title_mapping: VideoTitleMapping = Field(
        default_factory=VideoTitleMapping,
        description="Конфигурация маппинга названий",
    )
    platforms: dict[str, PlatformConfig] = Field(
        default_factory=dict,
        description="Конфигурации платформ",
    )
    upload_settings: UploadSettings = Field(
        default_factory=UploadSettings,
        description="Настройки загрузки",
    )

    @model_validator(mode="after")
    def validate_platforms(self) -> "AppConfig":
        """Валидация конфигураций платформ."""
        for platform_name, platform_config in self.platforms.items():
            if not isinstance(platform_config, PlatformConfig):
                raise ValueError(f"Платформа {platform_name} должна быть экземпляром PlatformConfig")
            if not platform_config.validate():
                raise ValueError(f"Ошибка валидации платформы {platform_name}")
        return self

    def validate_all(self) -> bool:
        """Валидация всех конфигураций"""
        try:
            self.validate_platforms()
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка валидации: {e}")
            return False


class UnifiedConfigLoader:
    """Загрузчик унифицированной конфигурации"""

    def __init__(self, config_file: str = "config/app_config.json"):
        self.config_file = config_file
        self.logger = logger

    def load_config(self) -> AppConfig:
        """Загрузка конфигурации из JSON файла"""
        try:
            if not os.path.exists(self.config_file):
                raise FileNotFoundError(f"Файл конфигурации не найден: {self.config_file}")

            with open(self.config_file, encoding="utf-8") as f:
                data = json.load(f)

            self.logger.info(f"✅ Конфигурация загружена из {self.config_file}")

            # Создаем объекты конфигурации
            app_config = self._create_app_config(data)

            # Валидируем конфигурацию
            if not app_config.validate_all():
                raise ValueError("Ошибка валидации конфигурации")

            return app_config

        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
            raise

    def _load_external_credentials(self, credentials_file: str) -> dict[str, Any]:
        """Загрузка credentials из внешнего файла"""
        try:
            if not os.path.exists(credentials_file):
                self.logger.warning(f"⚠️ Файл с credentials не найден: {credentials_file}")
                return {}

            with open(credentials_file, encoding="utf-8") as f:
                data = json.load(f)

            self.logger.info(f"✅ Credentials загружены из {credentials_file}")
            return data

        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки credentials из {credentials_file}: {e}")
            return {}

    def _create_app_config(self, data: dict[str, Any]) -> AppConfig:
        """Создание объекта AppConfig из данных JSON"""

        # Создаем конфигурацию маппинга названий
        mapping_data = data.get("video_title_mapping", {})
        video_title_mapping = VideoTitleMapping(**mapping_data)

        # Создаем конфигурации платформ
        platforms_data = data.get("platforms", {})
        platforms: dict[str, PlatformConfig] = {}

        # Получаем общие настройки загрузки для использования в платформах
        upload_data = data.get("upload_settings", {})

        # YouTube конфигурация
        if "youtube" in platforms_data:
            youtube_data = platforms_data["youtube"]

            # Единый файл с YouTube-конфигурацией и скоупами
            yt_bundle_path = youtube_data.get("credentials_file", "config/youtube_creds.json")
            yt_bundle_data: dict[str, Any] = {}
            if yt_bundle_path:
                yt_bundle_data = self._load_external_credentials(yt_bundle_path) or {}

            # Если bundle содержит сами секреты (client_secrets) и/или token, используем один общий файл
            is_bundle_with_embedded = isinstance(yt_bundle_data, dict) and (
                "client_secrets" in yt_bundle_data or "token" in yt_bundle_data
            )

            if is_bundle_with_embedded:
                client_secrets_file = yt_bundle_path
                credentials_file = yt_bundle_path
            else:
                # Достаём пути и скоупы: приоритет bundled ссылки; затем поля youtube секции; затем значения по умолчанию
                client_secrets_file = (
                    yt_bundle_data.get("client_secrets_file")
                    or youtube_data.get("client_secrets_file")
                    or "config/youtube_creds.json"
                )
                credentials_file = (
                    yt_bundle_data.get("token_file")
                    or yt_bundle_data.get("credentials_file")
                    or youtube_data.get("credentials_file")
                    or "config/youtube_creds.json"
                )
            # Источник scopes: сперва из bundle (top-level), затем из bundle.token.scopes,
            # иначе значения по умолчанию
            scopes = (
                yt_bundle_data.get("scopes")
                or (yt_bundle_data.get("token", {}) or {}).get("scopes")
                or [
                    "https://www.googleapis.com/auth/youtube.upload",
                    "https://www.googleapis.com/auth/youtube.force-ssl",
                ]
            )

            platforms["youtube"] = YouTubeConfig(
                enabled=youtube_data.get("enabled", True),
                client_secrets_file=client_secrets_file,
                credentials_file=credentials_file,
                scopes=scopes,
                default_privacy=youtube_data.get("default_privacy", "unlisted"),
                default_language=youtube_data.get("default_language", "ru"),
            )

        # VK конфигурация
        if "vk" in platforms_data:
            vk_data = platforms_data["vk"]

            # Загружаем VK credentials из отдельного файла, если указан
            access_token = vk_data.get("access_token", "")
            if not access_token and vk_data.get("credentials_file"):
                credentials_data = self._load_external_credentials(vk_data["credentials_file"])
                if credentials_data:
                    access_token = credentials_data.get("access_token", "")
                    if access_token:
                        self.logger.info("✅ VK access_token загружен из внешнего файла")

            platforms["vk"] = VKConfig(
                enabled=vk_data.get("enabled", True),
                access_token=access_token,
                group_id=vk_data.get("group_id"),
                album_id=None,  # Не используется, берется из правил маппинга
                name="",  # Не используется
                description="",  # Не используется
                privacy_view=str(vk_data.get("default_privacy", "0")),
                privacy_comment=vk_data.get("privacy_comment", "1"),
                no_comments=vk_data.get("no_comments", False),
                repeat=vk_data.get("repeat", False),
            )

        # Настройки загрузки
        upload_settings = UploadSettings(**upload_data)

        # Создаем AppConfig с валидацией Pydantic
        return AppConfig(
            video_title_mapping=video_title_mapping,
            platforms=platforms,
            upload_settings=upload_settings,
        )

    def save_config(self, config: AppConfig) -> bool:
        """Сохранение конфигурации в JSON файл"""
        try:
            data = {
                "video_title_mapping": config.video_title_mapping.model_dump(),
                "platforms": {},
                "upload_settings": config.upload_settings.model_dump(),
            }

            # Добавляем конфигурации платформ
            for _platform_name, platform_config in config.platforms.items():
                if isinstance(platform_config, YouTubeConfig):
                    # Пишем единый credentials_file
                    data["platforms"]["youtube"] = {
                        "enabled": platform_config.enabled,
                        "credentials_file": platform_config.credentials_file,
                        "default_language": platform_config.default_language,
                    }
                elif isinstance(platform_config, VKConfig):
                    data["platforms"]["vk"] = {
                        "enabled": platform_config.enabled,
                        "credentials_file": "config/vk_creds.json",
                        "group_id": platform_config.group_id,
                        "privacy_comment": platform_config.privacy_comment,
                        "no_comments": platform_config.no_comments,
                        "repeat": platform_config.repeat,
                    }

            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"✅ Конфигурация сохранена в {self.config_file}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения конфигурации: {e}")
            return False


# Глобальный экземпляр загрузчика
_config_loader = None


def get_config_loader() -> UnifiedConfigLoader:
    """Получение глобального экземпляра загрузчика конфигурации"""
    global _config_loader
    if _config_loader is None:
        _config_loader = UnifiedConfigLoader()
    return _config_loader


def load_app_config() -> AppConfig:
    """Удобная функция для загрузки конфигурации приложения"""
    loader = get_config_loader()
    return loader.load_config()
