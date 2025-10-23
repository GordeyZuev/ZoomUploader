"""
Конфигурация базы данных (совместимость с Pydantic Settings)
"""

from config.settings import settings


class DatabaseConfig:
    """Конфигурация подключения к PostgreSQL (совместимость)"""

    def __init__(self, db_settings=None):
        if db_settings is None:
            db_settings = settings.database

        self.host = db_settings.host
        self.port = db_settings.port
        self.database = db_settings.database
        self.username = db_settings.username
        self.password = db_settings.password

    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        """Создание конфигурации из Pydantic Settings"""
        return cls(settings.database)

    @property
    def url(self) -> str:
        """URL для подключения к базе данных"""
        return settings.database.url

    @property
    def sync_url(self) -> str:
        """Синхронный URL для Alembic"""
        return settings.database.sync_url
