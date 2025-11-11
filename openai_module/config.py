"""Конфигурация OpenAI API"""

import json
import os
from dataclasses import dataclass

from logger import get_logger

logger = get_logger()


@dataclass
class OpenAIConfig:
    """Конфигурация OpenAI API (только для Whisper)"""

    api_key: str
    whisper_model: str = "whisper-1"  # Модель Whisper
    retry_attempts: int = 2  # Количество попыток при ошибке
    retry_delay: float = 1.0  # Задержка между попытками (секунды)
    max_file_size_mb: int = 25  # Максимальный размер файла для Whisper API
    audio_bitrate: str = "64k"  # Битрейт для сжатого аудио
    audio_sample_rate: int = 16000  # Частота дискретизации (16kHz для Whisper)
    timeout: float = 1200.0  # Таймаут для запросов к OpenAI API (20 минут по умолчанию)
    # Для больших файлов (20+ МБ, 40+ минут) может потребоваться больше времени

    @classmethod
    def from_file(cls, config_file: str = "config/openai_creds.json") -> "OpenAIConfig":
        """Загрузка конфигурации из файла"""
        try:
            if not os.path.exists(config_file):
                raise FileNotFoundError(
                    f"Файл конфигурации OpenAI не найден: {config_file}\n"
                    f"Создайте файл с содержимым:\n"
                    f'{{"api_key": "your-api-key-here"}}'
                )

            with open(config_file, encoding='utf-8') as f:
                data = json.load(f)

            api_key = data.get("api_key", "")
            if not api_key:
                raise ValueError("API ключ OpenAI не указан в конфигурации")

            return cls(
                api_key=api_key,
                whisper_model=data.get("whisper_model", "whisper-1"),
                retry_attempts=data.get("retry_attempts", 2),
                retry_delay=data.get("retry_delay", 1.0),
                max_file_size_mb=data.get("max_file_size_mb", 25),
                audio_bitrate=data.get("audio_bitrate", "64k"),
                audio_sample_rate=data.get("audio_sample_rate", 16000),
                timeout=data.get("timeout", 1200.0),  # 20 минут по умолчанию
            )

        except Exception as e:
            logger.error(f"❌ Ошибка загрузки конфигурации OpenAI: {e}")
            raise

    def validate(self) -> bool:
        """Валидация конфигурации"""
        if not self.api_key:
            logger.error("❌ API ключ OpenAI не указан")
            return False

        if self.audio_sample_rate not in [8000, 16000, 24000, 44100, 48000]:
            logger.warning(
                f"⚠️ Нестандартная частота дискретизации: {self.audio_sample_rate}. "
                f"Рекомендуется 16000 для Whisper API"
            )

        return True

