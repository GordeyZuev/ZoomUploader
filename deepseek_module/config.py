"""Конфигурация DeepSeek API (как прямой, так и через Fireworks) с валидацией через Pydantic"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from logger import get_logger

logger = get_logger()


class DeepSeekConfig(BaseSettings):
    """
    Конфигурация DeepSeek / Fireworks-DeepSeek API.

    Поддерживает как прямой DeepSeek API, так и через Fireworks.
    """

    model_config = SettingsConfigDict(
        env_file=None,  # Не используем .env файл
        extra="ignore",  # Игнорируем лишние поля
        case_sensitive=False,
    )

    # Обязательные параметры
    api_key: str = Field(..., description="DeepSeek API ключ")

    # Параметры подключения
    model: str = Field(
        default="deepseek-chat",
        description="Модель DeepSeek для использования",
    )
    base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="Base URL для API (DeepSeek или Fireworks endpoint)",
    )

    # Базовые параметры генерации
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Температура сэмплирования (0.0-2.0)",
    )
    max_tokens: int = Field(
        default=8000,
        ge=100,
        le=8192,
        description="Максимальное количество токенов (ограничение DeepSeek: 8192, используем 8000)",
    )

    # Дополнительные параметры для Fireworks DeepSeek
    top_p: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Top-p сэмплирование (0.0-1.0)",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        description="Top-k сэмплирование (Fireworks-специфичный параметр)",
    )
    presence_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description="Presence penalty (-2.0 до 2.0)",
    )
    frequency_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description="Frequency penalty (-2.0 до 2.0)",
    )
    reasoning_effort: Literal["low", "medium", "high", "none"] | None = Field(
        default=None,
        description="Уровень усилий для reasoning (Fireworks-специфичный параметр)",
    )
    seed: int | None = Field(
        default=None,
        description="Seed для детерминированных ответов",
    )

    # Таймауты
    timeout: float = Field(
        default=120.0,
        ge=1.0,
        description="Таймаут для запросов в секундах",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        """Валидация base_url."""
        if not v.startswith(("http://", "https://")):
            raise ValueError("base_url должен начинаться с http:// или https://")
        return v.rstrip("/")

    @model_validator(mode="after")
    def validate_config(self) -> DeepSeekConfig:
        """Валидация зависимостей между полями."""
        # Проверка, что если используется Fireworks, то можно использовать Fireworks-специфичные параметры
        if self.top_k is not None or self.reasoning_effort is not None:
            base = (self.base_url or "").lower()
            if "fireworks.ai" not in base:
                logger.warning(
                    "⚠️ Fireworks-специфичные параметры (top_k, reasoning_effort) указаны, "
                    "но base_url не указывает на Fireworks. Эти параметры могут не работать."
                )

        return self

    @classmethod
    def from_file(cls, config_file: str = "config/deepseek_creds.json") -> DeepSeekConfig:
        """
        Загрузка конфигурации DeepSeek из JSON файла.

        Args:
            config_file: Путь к файлу конфигурации

        Returns:
            DeepSeekConfig: Валидированная конфигурация

        Raises:
            FileNotFoundError: Если файл не найден
            ValueError: Если API ключ не указан или валидация не прошла
        """
        if not os.path.exists(config_file):
            raise FileNotFoundError(
                f"Файл конфигурации DeepSeek не найден: {config_file}\n"
                f"Создайте файл с содержимым:\n"
                f'{{"api_key": "your-api-key-here"}}'
            )

        with open(config_file, encoding="utf-8") as f:
            data = json.load(f)

        api_key = data.get("api_key", "")
        if not api_key:
            raise ValueError("API ключ DeepSeek не указан в конфигурации")

        # Pydantic автоматически валидирует при создании экземпляра
        try:
            return cls(api_key=api_key, **{k: v for k, v in data.items() if k != "api_key"})
        except Exception as e:
            logger.error(f"❌ Ошибка валидации конфигурации DeepSeek: {e}")
            raise

    def to_request_params(self, use_fireworks_extras: bool = False) -> dict[str, Any]:
        """
        Формирование словаря параметров для вызова chat.completions.create().

        Поддерживает DeepSeek и Fireworks DeepSeek (OpenAI-совместимый API).

        Args:
            use_fireworks_extras: Если True, включает Fireworks-специфичные параметры
                                 (top_k, reasoning_effort). По умолчанию False, так как
                                 стандартный OpenAI клиент их не поддерживает.

        Returns:
            dict: Параметры для API запроса
        """
        params: dict[str, Any] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        # Стандартные параметры OpenAI API
        if self.top_p is not None:
            params["top_p"] = self.top_p
        if self.presence_penalty is not None:
            params["presence_penalty"] = self.presence_penalty
        if self.frequency_penalty is not None:
            params["frequency_penalty"] = self.frequency_penalty

        # Fireworks-специфичные параметры (только если явно запрошено)
        # Они не поддерживаются стандартным OpenAI клиентом
        if use_fireworks_extras:
            if self.top_k is not None:
                params["top_k"] = self.top_k
            if self.reasoning_effort is not None:
                params["reasoning_effort"] = self.reasoning_effort

        # Seed для детерминированных ответов (поддерживается OpenAI API)
        if self.seed is not None:
            params["seed"] = self.seed
        else:
            # Логируем предупреждение, если параметры заданы, но не используются
            if (self.top_k is not None or self.reasoning_effort is not None) and not use_fireworks_extras:
                base = (self.base_url or "").lower()
                if "fireworks.ai" in base:
                    logger.debug(
                        "⚠️ Fireworks-специфичные параметры (top_k, reasoning_effort) "
                        "не передаются, так как OpenAI клиент их не поддерживает. "
                        "Используются только стандартные параметры OpenAI API."
                    )

        return params
