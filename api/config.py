"""Конфигурация FastAPI приложения."""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """Настройки API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="API_",
        case_sensitive=False,
        extra="ignore",
    )

    # API
    api_title: str = Field(default="LEAP API - Lecture Enhancement & Automation Platform", description="Название API")
    api_version: str = Field(default="0.9.1", description="Версия API")
    api_description: str = Field(
        default="AI-powered platform for intelligent educational video content processing", description="Описание API"
    )
    docs_url: str = Field(default="/docs", description="URL документации Swagger")
    redoc_url: str = Field(default="/redoc", description="URL документации ReDoc")
    openapi_url: str = Field(default="/openapi.json", description="URL OpenAPI схемы")

    # CORS
    cors_origins: list[str] = Field(default=["*"], description="Разрешенные CORS origins")
    cors_allow_credentials: bool = Field(default=True, description="Разрешить credentials в CORS")
    cors_allow_methods: list[str] = Field(default=["*"], description="Разрешенные HTTP методы")
    cors_allow_headers: list[str] = Field(default=["*"], description="Разрешенные HTTP заголовки")

    # Server
    host: str = Field(default="0.0.0.0", description="Хост сервера")
    port: int = Field(default=8000, ge=1, le=65535, description="Порт сервера")
    reload: bool = Field(default=False, description="Автоперезагрузка при изменениях")

    # Celery
    celery_broker_url: str = Field(default="redis://localhost:6379/0", description="URL брокера Celery")
    celery_result_backend: str = Field(default="redis://localhost:6379/0", description="Backend результатов Celery")

    # JWT
    jwt_secret_key: str = Field(
        default="your-secret-key-change-in-production",
        min_length=32,
        description="Секретный ключ для JWT (мин. 32 символа)",
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        default="HS256", description="Алгоритм подписи JWT"
    )
    jwt_access_token_expire_minutes: int = Field(
        default=30, ge=1, le=1440, description="Время жизни access токена (минуты)"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, ge=1, le=30, description="Время жизни refresh токена (дни)"
    )

    # Security
    bcrypt_rounds: int = Field(default=12, ge=4, le=31, description="Раунды bcrypt хеширования")

    # Rate Limiting
    rate_limit_enabled: bool = Field(default=True, description="Включить rate limiting")
    rate_limit_per_minute: int = Field(default=60, ge=1, description="Лимит запросов в минуту")
    rate_limit_per_hour: int = Field(default=1000, ge=1, description="Лимит запросов в час")

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Валидация секретного ключа JWT."""
        if v == "your-secret-key-change-in-production":
            import warnings

            warnings.warn(
                "Using default JWT secret key! Change it in production via API_JWT_SECRET_KEY env variable",
                stacklevel=2,
            )
        if len(v) < 32:
            raise ValueError("JWT secret key must be at least 32 characters long")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Парсинг CORS origins из строки."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


# Singleton instance
_settings_instance: APISettings | None = None


def get_settings() -> APISettings:
    """Получить настройки API (singleton)."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = APISettings()
    return _settings_instance
