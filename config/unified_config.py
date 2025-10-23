"""
Унифицированная система конфигурации
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

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

    enabled: bool = True
    client_secrets_file: str = "config/youtube_client_secrets.json"
    credentials_file: str = "config/youtube_credentials.json"
    scopes: list[str] = None
    default_privacy: str = "private"
    default_language: str = "ru"

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = [
                'https://www.googleapis.com/auth/youtube.upload',
                'https://www.googleapis.com/auth/youtube.force-ssl',
            ]

    def validate(self) -> bool:
        """Валидация конфигурации YouTube"""
        if not self.enabled:
            return True

        if not os.path.exists(self.client_secrets_file):
            logger.warning(f"⚠️ Файл с секретами клиента не найден: {self.client_secrets_file}")
            # Не блокируем загрузку, просто предупреждаем

        if not self.scopes:
            logger.warning("⚠️ Не указаны scopes для YouTube API")
            # Не блокируем загрузку

        if self.default_privacy not in ['private', 'unlisted', 'public']:
            logger.error(f"❌ Неверный статус приватности: {self.default_privacy}")
            return False

        return True


@dataclass
class VKConfig(PlatformConfig):
    """Конфигурация VK API"""

    enabled: bool = True
    access_token: str = ""
    group_id: int | None = None
    album_id: int | None = None
    name: str = ""
    description: str = ""
    privacy_view: str = "0"
    privacy_comment: str = "1"
    no_comments: bool = False
    repeat: bool = False

    def validate(self) -> bool:
        """Валидация конфигурации VK"""
        if not self.enabled:
            return True

        if not self.access_token:
            logger.warning("⚠️ VK access_token не указан")
            # Не блокируем загрузку, просто предупреждаем

        if self.privacy_view not in ['0', '1', '2']:
            logger.error(f"❌ Неверный privacy_view: {self.privacy_view}")
            return False

        if self.privacy_comment not in ['0', '1', '2']:
            logger.error(f"❌ Неверный privacy_comment: {self.privacy_comment}")
            return False

        return True


@dataclass
class UploadSettings:
    """Настройки загрузки"""

    max_file_size_mb: int = 5000
    supported_formats: list[str] = None
    retry_attempts: int = 3
    retry_delay: int = 5
    interactive_mode: bool = True
    default_privacy: str = "private"

    def __post_init__(self):
        if self.supported_formats is None:
            self.supported_formats = ['mp4', 'avi', 'mov', 'mkv', 'webm', 'm4v']

    def validate_file(self, file_path: str) -> tuple[bool, str]:
        """Валидация файла перед загрузкой"""
        if not os.path.exists(file_path):
            return False, "Файл не существует"

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > self.max_file_size_mb:
            return False, f"Файл слишком большой: {file_size_mb:.1f}MB > {self.max_file_size_mb}MB"

        file_ext = os.path.splitext(file_path)[1].lower().lstrip('.')
        if file_ext not in self.supported_formats:
            return False, f"Неподдерживаемый формат: {file_ext}"

        return True, "OK"


@dataclass
class VideoTitleMapping:
    """Конфигурация маппинга названий видео"""

    mapping_rules: list[dict[str, Any]]
    default_rules: dict[str, Any]
    date_format: str = "DD.MM.YYYY"
    thumbnail_directory: str = "thumbnails/"


@dataclass
class AppConfig:
    """Главная конфигурация приложения"""

    video_title_mapping: VideoTitleMapping
    platforms: dict[str, PlatformConfig]
    upload_settings: UploadSettings

    def validate_all(self) -> bool:
        """Валидация всех конфигураций"""
        valid = True

        for platform_name, platform_config in self.platforms.items():
            if not platform_config.validate():
                logger.error(f"❌ Ошибка валидации платформы {platform_name}")
                valid = False

        return valid


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

            with open(self.config_file, encoding='utf-8') as f:
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

            with open(credentials_file, encoding='utf-8') as f:
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
        video_title_mapping = VideoTitleMapping(
            mapping_rules=mapping_data.get("mapping_rules", []),
            default_rules=mapping_data.get("default_rules", {}),
            date_format=mapping_data.get("date_format", "DD.MM.YYYY"),
            thumbnail_directory=mapping_data.get("thumbnail_directory", "thumbnails/"),
        )

        # Создаем конфигурации платформ
        platforms_data = data.get("platforms", {})
        platforms = {}

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
                'client_secrets' in yt_bundle_data or 'token' in yt_bundle_data
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
                    'https://www.googleapis.com/auth/youtube.upload',
                    'https://www.googleapis.com/auth/youtube.force-ssl',
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

        # Настройки загрузки (upload_data уже определен выше)
        upload_settings = UploadSettings(
            max_file_size_mb=upload_data.get("max_file_size_mb", 5000),
            supported_formats=upload_data.get("supported_formats", ['mp4', 'avi', 'mov']),
            retry_attempts=upload_data.get("retry_attempts", 3),
            retry_delay=upload_data.get("retry_delay", 5),
            interactive_mode=upload_data.get("interactive_mode", True),
            default_privacy=upload_data.get("default_privacy", "unlisted"),
        )

        return AppConfig(
            video_title_mapping=video_title_mapping,
            platforms=platforms,
            upload_settings=upload_settings,
        )

    def save_config(self, config: AppConfig) -> bool:
        """Сохранение конфигурации в JSON файл"""
        try:
            data = {
                "video_title_mapping": {
                    "mapping_rules": config.video_title_mapping.mapping_rules,
                    "default_rules": config.video_title_mapping.default_rules,
                    "date_format": config.video_title_mapping.date_format,
                    "thumbnail_directory": config.video_title_mapping.thumbnail_directory,
                },
                "platforms": {},
                "upload_settings": {
                    "max_file_size_mb": config.upload_settings.max_file_size_mb,
                    "supported_formats": config.upload_settings.supported_formats,
                    "retry_attempts": config.upload_settings.retry_attempts,
                    "retry_delay": config.upload_settings.retry_delay,
                    "interactive_mode": config.upload_settings.interactive_mode,
                    "default_privacy": config.upload_settings.default_privacy,
                },
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

            with open(self.config_file, 'w', encoding='utf-8') as f:
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
