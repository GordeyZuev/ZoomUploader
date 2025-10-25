from abc import ABC, abstractmethod
from dataclasses import dataclass

from logger import get_logger

logger = get_logger()


class PlatformConfig(ABC):
    """Базовый класс конфигурации платформы"""

    @abstractmethod
    def validate(self) -> bool:
        """Валидация конфигурации"""
        pass


@dataclass
class YouTubeConfig(PlatformConfig):
    """Конфигурация YouTube API"""

    client_secrets_file: str = "youtube_client_secrets.json"
    credentials_file: str = "youtube_credentials.json"
    scopes: list[str] | None = None
    default_privacy: str = "private"
    default_language: str = "ru"

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = [
                'https://www.googleapis.com/auth/youtube.upload',
                'https://www.googleapis.com/auth/youtube.force-ssl',
            ]

    def validate(self) -> bool:
        """Валидация конфигурации"""
        import os

        if not os.path.exists(self.client_secrets_file):
            logger.warning(f"⚠️ Файл с секретами клиента не найден: {self.client_secrets_file}")

        if not self.scopes:
            logger.warning("⚠️ Не указаны scopes для YouTube API")

        if self.default_privacy not in ['private', 'unlisted', 'public']:
            logger.error(f"❌ Неверный статус приватности: {self.default_privacy}")
            return False

        return True


@dataclass
class VKConfig(PlatformConfig):
    """Конфигурация VK API"""

    access_token: str = ""
    app_id: str = "54249533"  # ID приложения VK
    scope: str = "video,groups,wall"  # Права доступа
    group_id: int | None = None
    album_id: int | None = None
    name: str = ""
    description: str = ""
    privacy_view: str = "0"
    privacy_comment: str = "1"
    no_comments: bool = False
    repeat: bool = False

    def validate(self) -> bool:
        """Валидация конфигурации"""
        if not self.access_token:
            logger.warning("⚠️ VK access_token не указан")

        if not self.app_id:
            logger.warning("⚠️ VK app_id не указан")

        if not self.scope:
            logger.warning("⚠️ VK scope не указан")

        if self.privacy_view not in ['0', '1', '2']:
            logger.error(f"❌ Неверный privacy_view: {self.privacy_view}")
            return False

        if self.privacy_comment not in ['0', '1', '2']:
            logger.error(f"❌ Неверный privacy_comment: {self.privacy_comment}")
            return False

        return True


@dataclass
class UploadConfig:
    """Общая конфигурация системы загрузки"""

    youtube: YouTubeConfig | None = None
    vk: VKConfig | None = None
    max_file_size_mb: int = 5000
    supported_formats: list[str] | None = None
    retry_attempts: int = 3
    retry_delay: int = 5

    def __post_init__(self):
        if self.supported_formats is None:
            self.supported_formats = ['mp4', 'avi', 'mov', 'mkv', 'webm', 'm4v']

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
        """Создание конфигурации из унифицированного конфига приложения"""

        # Создаем конфигурации платформ
        youtube = None
        vk = None

        if "youtube" in app_config.platforms:
            youtube_platform = app_config.platforms["youtube"]
            youtube = YouTubeConfig(
                client_secrets_file=youtube_platform.client_secrets_file,
                credentials_file=youtube_platform.credentials_file,
                scopes=youtube_platform.scopes,
                default_privacy=youtube_platform.default_privacy,
                default_language=youtube_platform.default_language,
            )

        if "vk" in app_config.platforms:
            vk_platform = app_config.platforms["vk"]
            vk = VKConfig(
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
