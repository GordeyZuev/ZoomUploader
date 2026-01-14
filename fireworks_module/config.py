"""Fireworks Audio Inference API configuration"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from logger import get_logger

logger = get_logger()


class FireworksConfig(BaseSettings):
    """Fireworks Audio API configuration. Docs: https://docs.fireworks.ai/api-reference/audio-transcriptions"""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    api_key: str = Field(..., description="Fireworks API ключ")
    model: Literal["whisper-v3", "whisper-v3-turbo"] = Field(
        default="whisper-v3-turbo",
        description="ASR модель для транскрибации",
    )
    base_url: str = Field(
        default="https://audio-turbo.api.fireworks.ai",
        description="Base URL для API (зависит от модели)",
    )
    account_id: str | None = Field(
        default=None,
        description="Account ID для Batch API (из Fireworks dashboard)",
    )
    batch_base_url: str = Field(
        default="https://audio-batch.api.fireworks.ai",
        description="Base URL для Batch API",
    )

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
        """Validation and normalization of timestamp_granularities."""
        if v is None:
            return None
        if isinstance(v, str):
            # Support string "word" or "word,segment"
            return [g.strip() for g in v.split(",") if g.strip()]
        if isinstance(v, list):
            # Filter only valid values
            valid = {"word", "segment"}
            return [g for g in v if g in valid]
        return None

    @field_validator("base_url", mode="after")
    @classmethod
    def validate_base_url(cls, v: str, info: Any) -> str:
        """Automatically sets base_url depending on the model."""
        model = info.data.get("model", "whisper-v3-turbo")
        if model == "whisper-v3-turbo":
            return "https://audio-turbo.api.fireworks.ai"
        return "https://audio-prod.api.fireworks.ai"

    @model_validator(mode="after")
    def validate_config(self) -> FireworksConfig:
        """
        Validation of dependencies between fields according to the documentation.

        Правила:
        1. verbose_json требует timestamp_granularities
        2. diarize=true требует verbose_json и word в timestamp_granularities
        3. min_speakers/max_speakers требуют diarize=true
        """
        # Rule 1: verbose_json requires timestamp_granularities
        if self.response_format == "verbose_json":
            if not self.timestamp_granularities:
                logger.warning(
                    "⚠️ response_format = 'verbose_json', but timestamp_granularities is not specified. "
                    "Setting default value: ['segment']"
                )
                self.timestamp_granularities = ["segment"]

        # Rule 2: diarize=true requires verbose_json and word
        if self.diarize:
            if self.response_format != "verbose_json":
                raise ValueError(
                    f"diarize=true requires response_format='verbose_json', but '{self.response_format}' is specified"
                )
            if not self.timestamp_granularities or "word" not in self.timestamp_granularities:
                raise ValueError(
                    f"diarize=true requires timestamp_granularities to include 'word', "
                    f"but {self.timestamp_granularities} is specified"
                )

        # Rule 3: min_speakers/max_speakers require diarize=true
        if (self.min_speakers is not None or self.max_speakers is not None) and not self.diarize:
            logger.warning(
                "min_speakers/max_speakers are specified, but diarize=false. These parameters will be ignored."
            )

        # Rule 4: max_speakers must be >= min_speakers
        if self.min_speakers is not None and self.max_speakers is not None and self.max_speakers < self.min_speakers:
            raise ValueError(f"max_speakers ({self.max_speakers}) must be greater than or equal to min_speakers ({self.min_speakers})")

        return self

    @classmethod
    def from_file(cls, config_file: str = "config/fireworks_creds.json") -> FireworksConfig:
        """Download Fireworks configuration from a JSON file."""
        if not os.path.exists(config_file):
            raise FileNotFoundError(
                f"Fireworks configuration file not found: {config_file}\n"
                f"Create a file with the following content:\n"
                f'{{"api_key": "your-fireworks-api-key"}}'
            )

        with open(config_file, encoding="utf-8") as fp:
            data = json.load(fp)

        api_key = data.pop("api_key", "")
        if not api_key:
            raise ValueError("Fireworks API key not specified in configuration")

        try:
            return cls(api_key=api_key, **data)
        except Exception as e:
            logger.error(f"Validation error: {e}")
            raise

    def to_request_params(self) -> dict[str, Any]:
        """
        Generate a dictionary of parameters for the Fireworks API.
        Converts internal parameters to the format expected by the API.
        """
        params: dict[str, Any] = {
            "language": self.language,
            "response_format": self.response_format,
        }

        if self.timestamp_granularities:
            params["timestamp_granularities"] = self.timestamp_granularities

        if self.alignment_model:
            params["alignment_model"] = self.alignment_model

        if self.temperature is not None:
            params["temperature"] = self.temperature

        if self.vad_model:
            params["vad_model"] = self.vad_model

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
