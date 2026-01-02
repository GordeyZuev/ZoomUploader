from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Настройки базы данных"""

    host: str = Field(default="localhost", description="Хост базы данных")
    port: int = Field(default=5432, description="Порт базы данных")
    database: str = Field(default="zoom_manager", description="Название базы данных")
    username: str = Field(default="postgres", description="Имя пользователя")
    password: str = Field(default="", description="Пароль")

    @property
    def url(self) -> str:
        """URL для подключения к базе данных"""
        return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        """Синхронный URL для Alembic"""
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"


class LoggingSettings(BaseSettings):
    """Настройки логирования"""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Уровень логирования"
    )
    format: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", description="Формат логов")
    file_path: str | None = Field(default=None, description="Путь к файлу логов (если None - только консоль)")


MEDIA_ROOT = "media"


class ProcessingSettings(BaseSettings):
    """Настройки обработки видео"""

    input_dir: str = Field(default=f"{MEDIA_ROOT}/video/unprocessed", description="Директория входящих видео")
    output_dir: str = Field(default=f"{MEDIA_ROOT}/video/processed", description="Директория обработанных видео")
    temp_dir: str = Field(default=f"{MEDIA_ROOT}/video/temp_processing", description="Временная директория")

    # Настройки FFmpeg - только обрезка без изменения качества
    video_codec: str = Field(default="copy", description="Видео кодек (copy = без перекодирования)")
    audio_codec: str = Field(default="copy", description="Аудио кодек (copy = без перекодирования)")
    video_bitrate: str = Field(default="original", description="Битрейт видео (original = не изменять)")
    audio_bitrate: str = Field(default="original", description="Битрейт аудио (original = не изменять)")
    fps: int = Field(default=0, description="FPS (0 = не изменять)")
    resolution: str = Field(default="original", description="Разрешение (original = не изменять)")

    # Настройки детекции звука
    silence_threshold: float = Field(default=-40.0, description="Порог тишины в дБ")
    min_silence_duration: float = Field(default=2.0, description="Минимальная длительность тишины в секундах")
    padding_before: float = Field(default=5.0, description="Отступ до звука в секундах")
    padding_after: float = Field(default=5.0, description="Отступ после звука в секундах")

    # Настройки обрезки
    remove_intro: bool = Field(default=True, description="Удалять вступление")
    remove_outro: bool = Field(default=True, description="Удалять заключение")
    intro_duration: float = Field(default=30.0, description="Длительность вступления в секундах")
    outro_duration: float = Field(default=30.0, description="Длительность заключения в секундах")

    # Дополнительные настройки
    keep_temp_files: bool = Field(default=False, description="Сохранять временные файлы")


class ZoomSettings(BaseSettings):
    """Настройки Zoom API"""

    config_file: str = Field(default="config/zoom_creds.json", description="Путь к файлу конфигурации Zoom")
    download_dir: str = Field(
        default=f"{MEDIA_ROOT}/video/unprocessed", description="Директория для скачивания записей"
    )


class UploadSettings(BaseSettings):
    """Настройки загрузки на платформы"""

    youtube_config_file: str = Field(
        default="config/youtube_creds.json", description="Путь к файлу конфигурации YouTube"
    )
    vk_config_file: str = Field(default="config/vk_creds.json", description="Путь к файлу конфигурации VK")


class ZoomConfig:
    """Конфигурация аккаунта Zoom"""

    def __init__(self, account: str, account_id: str, client_id: str, client_secret: str):
        self.account = account
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret


# Функции для работы с конфигурацией Zoom (совместимость)
def load_config_from_file(config_file: str) -> dict:
    """Загрузка конфигураций Zoom из файла (совместимость)"""
    import json
    import os

    if not os.path.exists(config_file):
        return {}

    with open(config_file, encoding="utf-8") as f:
        data = json.load(f)

    configs = {}

    # Обрабатываем структуру с массивом аккаунтов
    if "accounts" in data:
        for account_data in data["accounts"]:
            account = account_data["account"]
            configs[account] = ZoomConfig(
                account=account_data["account"],
                account_id=account_data["account_id"],
                client_id=account_data["client_id"],
                client_secret=account_data["client_secret"],
            )
    else:
        # Обрабатываем старую структуру со словарем
        for account, config_data in data.items():
            configs[account] = ZoomConfig(
                account=config_data["account"],
                account_id=config_data["account_id"],
                client_id=config_data["client_id"],
                client_secret=config_data["client_secret"],
            )

    return configs


def get_config_by_account(account: str, configs: dict) -> ZoomConfig:
    """Получение конфигурации по аккаунту (совместимость)"""
    if account not in configs:
        raise ValueError(f"Конфигурация для аккаунта {account} не найдена")
    return configs[account]


class AppSettings(BaseSettings):
    """Основные настройки приложения"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # Поднастройки
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    zoom: ZoomSettings = Field(default_factory=ZoomSettings)
    upload: UploadSettings = Field(default_factory=UploadSettings)

    # Общие настройки
    app_name: str = Field(default="Zoom Manager", description="Название приложения")
    version: str = Field(default="1.0.0", description="Версия приложения")
    debug: bool = Field(default=False, description="Режим отладки")
    timezone: str = Field(default="Europe/Moscow", description="Часовой пояс для отображения времени")


# Глобальный экземпляр настроек
settings = AppSettings()
