"""Конфигурация для Fireworks Audio Inference API с валидацией через Pydantic"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from logger import get_logger

logger = get_logger()


class FireworksConfig(BaseSettings):
    """
    Параметры подключения и поведения модели Fireworks.

    Все параметры соответствуют документации Fireworks AI Audio API:
    https://docs.fireworks.ai/api-reference/audio-transcriptions
    """

    model_config = SettingsConfigDict(
        env_file=None,  # Не используем .env файл
        extra="ignore",  # Игнорируем лишние поля
        case_sensitive=False,
    )

    # Обязательные параметры
    api_key: str = Field(..., description="Fireworks API ключ")

    # Параметры подключения
    model: Literal["whisper-v3", "whisper-v3-turbo"] = Field(
        default="whisper-v3-turbo",
        description="ASR модель для транскрибации",
    )
    base_url: str = Field(
        default="https://audio-turbo.api.fireworks.ai",
        description="Base URL для API (зависит от модели)",
    )

    # Параметры транскрибации из документации
    language: str | None = Field(
        default="ru",
        description="Язык транскрибации (код языка ISO 639-1)",
    )
    response_format: Literal["json", "text", "srt", "verbose_json", "vtt"] = Field(
        default="verbose_json",
        description="Формат ответа от API",
    )
    timestamp_granularities: list[Literal["word", "segment"]] | None = Field(
        default=None,
        description="Гранулярность временных меток (требуется для verbose_json)",
    )
    alignment_model: Literal["mms_fa", "tdnn_ffn", "gentle"] | None = Field(
        default=None,
        description="Модель выравнивания (mms_fa для мультиязычности, tdnn_ffn/gentle для английского)",
    )
    diarize: bool = Field(
        default=False,
        description="Включить диаризацию спикеров (требует verbose_json и word в timestamp_granularities)",
    )
    vad_model: Literal["silero", "whisperx-pyannet"] | None = Field(
        default=None,
        description="Модель VAD (Voice Activity Detection)",
    )
    temperature: float | list[float] | None = Field(
        default=0.0,
        description="Температура сэмплирования (0.0-1.0) или список для fallback decoding",
    )
    prompt: str | None = Field(
        default=None,
        description="Промпт для улучшения качества транскрибации",
    )
    preprocessing: Literal["none", "dynamic", "soft_dynamic", "bass_dynamic"] | None = Field(
        default=None,
        description="Режим предобработки аудио",
    )

    # Параметры диаризации (требуются только если diarize=True)
    min_speakers: int | None = Field(
        default=None,
        ge=1,
        description="Минимальное количество спикеров (требует diarize=true)",
    )
    max_speakers: int | None = Field(
        default=None,
        ge=1,
        description="Максимальное количество спикеров (требует diarize=true)",
    )

    # Ограничения и ретраи (внутренние параметры)
    max_file_size_mb: int = Field(
        default=1024,
        ge=1,
        description="Максимальный размер файла в МБ",
    )
    audio_bitrate: str = Field(
        default="64k",
        description="Битрейт аудио для обработки",
    )
    audio_sample_rate: int = Field(
        default=16000,
        ge=8000,
        le=48000,
        description="Частота дискретизации аудио (Гц)",
    )
    retry_attempts: int = Field(
        default=3,
        ge=1,
        description="Количество попыток при ошибке",
    )
    retry_delay: float = Field(
        default=2.0,
        ge=0.0,
        description="Базовая задержка для экспоненциальной задержки (секунды)",
    )

    @field_validator("timestamp_granularities", mode="before")
    @classmethod
    def validate_timestamp_granularities(cls, v: Any) -> list[str] | None:
        """Валидация и нормализация timestamp_granularities."""
        if v is None:
            return None
        if isinstance(v, str):
            # Поддержка строки "word" или "word,segment"
            return [g.strip() for g in v.split(",") if g.strip()]
        if isinstance(v, list):
            # Фильтруем только валидные значения
            valid = {"word", "segment"}
            return [g for g in v if g in valid]
        return None

    @field_validator("base_url", mode="after")
    @classmethod
    def validate_base_url(cls, v: str, info: Any) -> str:
        """Автоматически устанавливает base_url в зависимости от модели."""
        model = info.data.get("model", "whisper-v3-turbo")
        if model == "whisper-v3-turbo":
            return "https://audio-turbo.api.fireworks.ai"
        return "https://audio-prod.api.fireworks.ai"

    @model_validator(mode="after")
    def validate_config(self) -> FireworksConfig:
        """
        Валидация зависимостей между полями согласно документации.

        Правила:
        1. verbose_json требует timestamp_granularities
        2. diarize=true требует verbose_json и word в timestamp_granularities
        3. min_speakers/max_speakers требуют diarize=true
        """
        # Правило 1: verbose_json требует timestamp_granularities
        if self.response_format == "verbose_json":
            if not self.timestamp_granularities:
                logger.warning(
                    "⚠️ response_format = 'verbose_json', но timestamp_granularities не указан. "
                    "Устанавливаю значение по умолчанию: ['segment']"
                )
                self.timestamp_granularities = ["segment"]

        # Правило 2: diarize=true требует verbose_json и word
        if self.diarize:
            if self.response_format != "verbose_json":
                raise ValueError(
                    f"diarize=true требует response_format='verbose_json', но указан '{self.response_format}'"
                )
            if not self.timestamp_granularities or "word" not in self.timestamp_granularities:
                raise ValueError(
                    f"diarize=true требует, чтобы timestamp_granularities включал 'word', "
                    f"но указано: {self.timestamp_granularities}"
                )

        # Правило 3: min_speakers/max_speakers требуют diarize=true
        if (self.min_speakers is not None or self.max_speakers is not None) and not self.diarize:
            logger.warning(
                "⚠️ min_speakers/max_speakers указаны, но diarize=false. Эти параметры будут проигнорированы."
            )

        # Правило 4: max_speakers должен быть >= min_speakers
        if self.min_speakers is not None and self.max_speakers is not None and self.max_speakers < self.min_speakers:
            raise ValueError(f"max_speakers ({self.max_speakers}) должен быть >= min_speakers ({self.min_speakers})")

        return self

    @classmethod
    def from_file(cls, config_file: str = "config/fireworks_creds.json") -> FireworksConfig:
        """
        Загрузка конфигурации Fireworks из JSON файла.

        Поддерживает обратную совместимость со старыми ключами:
        - output_format -> response_format
        - timestamps -> timestamp_granularities
        """
        if not os.path.exists(config_file):
            raise FileNotFoundError(
                f"Файл конфигурации Fireworks не найден: {config_file}\n"
                f"Создайте файл с содержимым:\n"
                f'{{"api_key": "your-fireworks-api-key"}}'
            )

        with open(config_file, encoding="utf-8") as fp:
            data = json.load(fp)

        # Извлекаем api_key
        api_key = data.pop("api_key", "")
        if not api_key:
            raise ValueError("API ключ Fireworks не указан в конфигурации")

        # Совместимость с более ранними ключами
        if "output_format" in data and "response_format" not in data:
            data["response_format"] = data.pop("output_format")

        # Совместимость: timestamps -> timestamp_granularities
        timestamps_value = data.pop("timestamps", None)
        if timestamps_value is not None and "timestamp_granularities" not in data:
            if timestamps_value in ("none", None, ""):
                data["timestamp_granularities"] = []
            else:
                data["timestamp_granularities"] = [timestamps_value]

        # Создаем конфиг с валидацией Pydantic
        try:
            return cls(api_key=api_key, **data)
        except Exception as e:
            logger.error(f"❌ Ошибка валидации конфигурации: {e}")
            raise

    def to_request_params(self) -> dict[str, Any]:
        """
        Формирование словаря параметров для Fireworks API.

        Преобразует внутренние параметры в формат, ожидаемый API.
        """
        params: dict[str, Any] = {
            "language": self.language,
            "response_format": self.response_format,
        }

        # timestamp_granularities обязателен для verbose_json
        if self.timestamp_granularities:
            params["timestamp_granularities"] = self.timestamp_granularities

        if self.alignment_model:
            params["alignment_model"] = self.alignment_model

        if self.temperature is not None:
            params["temperature"] = self.temperature

        # VAD параметры
        if self.vad_model:
            params["vad_model"] = self.vad_model

        # Диаризация
        # Согласно документации, diarize должен быть строкой "true" или "false"
        params["diarize"] = "true" if self.diarize else "false"
        if self.diarize:
            if self.min_speakers is not None:
                params["min_speakers"] = self.min_speakers
            if self.max_speakers is not None:
                params["max_speakers"] = self.max_speakers

        if self.prompt:
            params["prompt"] = self.prompt

        if self.preprocessing:
            params["preprocessing"] = self.preprocessing

        return params
