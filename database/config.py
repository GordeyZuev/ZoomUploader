"""PostgreSQL connection configuration"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import settings


class DatabaseConfig(BaseSettings):
    """PostgreSQL connection configuration"""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    host: str = Field(
        default_factory=lambda: settings.database.host,
        description="Хост базы данных",
    )
    port: int = Field(
        default_factory=lambda: settings.database.port,
        ge=1,
        le=65535,
        description="Порт базы данных",
    )
    database: str = Field(
        default_factory=lambda: settings.database.database,
        description="Название базы данных",
    )
    username: str = Field(
        default_factory=lambda: settings.database.username,
        description="Имя пользователя",
    )
    password: str = Field(
        default_factory=lambda: settings.database.password,
        description="Пароль",
    )

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """
        Создание конфигурации из Pydantic Settings.

        Returns:
            DatabaseConfig: Конфигурация базы данных
        """
        return cls()

    @property
    def url(self) -> str:
        """
        URL для подключения к базе данных (асинхронный).

        Returns:
            str: PostgreSQL async URL
        """
        return f"postgresql+asyncpg://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        """
        Синхронный URL для Alembic.

        Returns:
            str: PostgreSQL sync URL
        """
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"
