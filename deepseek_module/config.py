"""Конфигурация DeepSeek API"""

import json
import os
from dataclasses import dataclass

from logger import get_logger

logger = get_logger()


@dataclass
class DeepSeekConfig:
    """Конфигурация DeepSeek API"""

    api_key: str
    model: str = "deepseek-chat"  # Модель DeepSeek
    base_url: str = "https://api.deepseek.com/v1"  # DeepSeek endpoint
    temperature: float = 0.0  # Минимальная температура для максимальной детерминированности
    max_tokens: int = 8000  # Ограничение DeepSeek: максимум 8192, используем 8000
    timeout: float = 120.0  # Таймаут для запросов

    @classmethod
    def from_file(cls, config_file: str = "config/deepseek_creds.json") -> "DeepSeekConfig":
        """Загрузка конфигурации из файла"""
        try:
            if not os.path.exists(config_file):
                raise FileNotFoundError(
                    f"Файл конфигурации DeepSeek не найден: {config_file}\n"
                    f"Создайте файл с содержимым:\n"
                    f'{{"api_key": "your-api-key-here"}}'
                )

            with open(config_file, encoding='utf-8') as f:
                data = json.load(f)

            api_key = data.get("api_key", "")
            if not api_key:
                raise ValueError("API ключ DeepSeek не указан в конфигурации")

            return cls(
                api_key=api_key,
                model=data.get("model", "deepseek-chat"),
                base_url=data.get("base_url", "https://api.deepseek.com/v1"),
                temperature=data.get("temperature", 0.1),
                max_tokens=data.get("max_tokens", 4000),
                timeout=data.get("timeout", 120.0),
            )

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки конфигурации DeepSeek: {e}")
            raise

    def validate(self) -> bool:
        """Валидация конфигурации"""
        if not self.api_key:
            logger.error("❌ API ключ DeepSeek не указан")
            return False

        if self.temperature < 0 or self.temperature > 2:
            logger.error("❌ Температура должна быть в диапазоне [0, 2]")
            return False

        if self.max_tokens < 100:
            logger.error("❌ max_tokens должен быть не менее 100")
            return False

        return True

