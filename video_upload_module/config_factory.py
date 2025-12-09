"""Фабрика конфигураций для загрузки видео с валидацией через Pydantic"""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.unified_config import PlatformConfig, VKConfig, YouTubeConfig
from logger import get_logger

logger = get_logger()


class YouTubeUploadConfig(PlatformConfig):
    """Конфигурация YouTube API для загрузки"""

    client_secrets_file: str = Field(
        default="youtube_client_secrets.json",
        description="Путь к файлу с секретами клиента",
    )
    credentials_file: str = Field(
        default="youtube_credentials.json",
        description="Путь к файлу с credentials",
    )
    scopes: list[str] = Field(
        default_factory=lambda: [
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtube.force-ssl',
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
        """Валидация конфигурации"""
        import os

        if not os.path.exists(self.client_secrets_file):
            logger.warning(f"⚠️ Файл с секретами клиента не найден: {self.client_secrets_file}")

        if self.default_privacy not in ['private', 'unlisted', 'public']:
            logger.error(f"❌ Неверный статус приватности: {self.default_privacy}")
            return False

        return True


class VKUploadConfig(PlatformConfig):
    """Конфигурация VK API для загрузки"""

    access_token: str = Field(
        default="",
        description="VK access token",
    )
    app_id: str = Field(
        default="54249533",
        description="ID приложения VK",
    )
    scope: str = Field(
        default="video,groups,wall",
        description="Права доступа",
    )
    group_id: int | None = Field(
        default=None,
        description="ID группы VK",
    )
    album_id: int | None = Field(
        default=None,
        description="ID альбома VK",
    )
    name: str = Field(
        default="",
        description="Название",
    )
    description: str = Field(
        default="",
        description="Описание",
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
        """Валидация конфигурации"""
        if not self.access_token:
            logger.warning("⚠️ VK access_token не указан")

        if not self.app_id:
            logger.warning("⚠️ VK app_id не указан")

        if not self.scope:
            logger.warning("⚠️ VK scope не указан")

        return True


class UploadConfig(BaseSettings):
    """Общая конфигурация системы загрузки"""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    youtube: YouTubeUploadConfig | None = Field(
        default=None,
        description="Конфигурация YouTube",
    )
    vk: VKUploadConfig | None = Field(
        default=None,
        description="Конфигурация VK",
    )
    max_file_size_mb: int = Field(
        default=5000,
        ge=1,
        description="Максимальный размер файла в МБ",
    )
    supported_formats: list[str] = Field(
        default_factory=lambda: ['mp4', 'avi', 'mov', 'mkv', 'webm', 'm4v'],
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

    def validate(self) -> bool:
        """Валидация всей конфигурации"""
        if self.youtube and not self.youtube.validate():
            return False

        if self.vk and not self.vk.validate():
            return False

        return True


class UploadConfigFactory:
    """Фабрика для создания конфигураций загрузки"""

    @staticmethod
    def from_app_config(app_config) -> UploadConfig:
        """
        Создание конфигурации из унифицированного конфига приложения.

        Args:
            app_config: AppConfig из unified_config

        Returns:
            UploadConfig: Конфигурация для загрузки
        """
        # Создаем конфигурации платформ
        youtube = None
        vk = None

        if "youtube" in app_config.platforms:
            youtube_platform = app_config.platforms["youtube"]
            if isinstance(youtube_platform, YouTubeConfig):
                youtube = YouTubeUploadConfig(
                    enabled=youtube_platform.enabled,
                    client_secrets_file=youtube_platform.client_secrets_file,
                    credentials_file=youtube_platform.credentials_file,
                    scopes=youtube_platform.scopes,
                    default_privacy=youtube_platform.default_privacy,
                    default_language=youtube_platform.default_language,
                )

        if "vk" in app_config.platforms:
            vk_platform = app_config.platforms["vk"]
            if isinstance(vk_platform, VKConfig):
                vk = VKUploadConfig(
                    enabled=vk_platform.enabled,
                    access_token=vk_platform.access_token,
                    app_id=getattr(vk_platform, 'app_id', '54249533'),
                    scope=getattr(vk_platform, 'scope', 'video,groups,wall'),
                    group_id=vk_platform.group_id,
                    album_id=vk_platform.album_id,
                    name=vk_platform.name,
                    description=vk_platform.description,
                    privacy_view=vk_platform.privacy_view,
                    privacy_comment=vk_platform.privacy_comment,
                    no_comments=vk_platform.no_comments,
                    repeat=vk_platform.repeat,
                )

        # Создаем общую конфигурацию
        upload_settings = app_config.upload_settings
        return UploadConfig(
            youtube=youtube,
            vk=vk,
            max_file_size_mb=upload_settings.max_file_size_mb,
            supported_formats=upload_settings.supported_formats,
            retry_attempts=upload_settings.retry_attempts,
            retry_delay=upload_settings.retry_delay,
        )
