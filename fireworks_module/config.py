"\"\"\"Конфигурация для Fireworks Audio Inference API\"\"\""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from logger import get_logger

logger = get_logger()


@dataclass
class FireworksConfig:
    """Параметры подключения и поведения модели Fireworks."""

    api_key: str
    model: str = "whisper-v3-turbo"
    base_url: str = "https://audio-turbo.api.fireworks.ai"

    # Параметры транскрибации
    language: str = "ru"
    response_format: str = "verbose_json"
    timestamp_granularities: list[str] | None = field(default_factory=lambda: ["segment"])
    alignment_model: str | None = None
    diarization: bool = False
    enable_vad: bool = False  # VAD разбивает аудио по-разному → недетерминированность
    vad_model: str | None = None  # "silero" (default) | "whisperx-pyannet" (Более точная)
    temperature: float | None = 0.0
    prompt: str | None = None
    preprocessing: str | None = None
    max_clip_len: float | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None

    # Ограничения и ретраи
    max_file_size_mb: int = 25
    audio_bitrate: str = "64k"
    audio_sample_rate: int = 16000
    retry_attempts: int = 2
    retry_delay: float = 2.0

    @classmethod
    def from_file(cls, config_file: str = "config/fireworks_creds.json") -> FireworksConfig:
        """Загрузка конфигурации Fireworks из файла."""
        if not os.path.exists(config_file):
            raise FileNotFoundError(
                f"Файл конфигурации Fireworks не найден: {config_file}\n"
                f"Создайте файл с содержимым:\n"
                f'{{"api_key": "your-fireworks-api-key"}}'
            )

        with open(config_file, encoding="utf-8") as fp:
            data = json.load(fp)

        api_key = data.pop("api_key", "")
        if not api_key:
            raise ValueError("API ключ Fireworks не указан в конфигурации")

        # Совместимость с более ранними ключами
        if "output_format" in data and "response_format" not in data:
            data["response_format"] = data.pop("output_format")

        timestamps_value = data.pop("timestamps", None)
        if timestamps_value is not None and "timestamp_granularities" not in data:
            # Fireworks ожидает список значений
            if timestamps_value in ("none", None, ""):
                data["timestamp_granularities"] = []
            else:
                data["timestamp_granularities"] = [timestamps_value]

        # enable_vad -> skip_vad (инверсия)
        enable_vad = data.pop("enable_vad", None)
        if enable_vad is not None:
            data["enable_vad"] = bool(enable_vad)

        # diarization -> diarize
        diarization = data.pop("diarization", None)
        if diarization is not None and "diarization" not in data:
            data["diarization"] = bool(diarization)

        return cls(api_key=api_key, **data)

    def validate(self) -> bool:
        """Проверка корректности конфигурации."""
        if not self.api_key:
            logger.error("❌ API ключ Fireworks не указан")
            return False

        if not self.response_format:
            self.response_format = "verbose_json"

        if self.timestamp_granularities is None:
            self.timestamp_granularities = ["segment"]

        if self.response_format not in {"text", "json", "verbose_json", "srt", "vtt"}:
            logger.warning(
                f"⚠️ Неподдерживаемый формат вывода '{self.response_format}'. "
                "Будет использован формат 'verbose_json'."
            )
            self.response_format = "verbose_json"

        # Сбрасываем некорректные значения временных меток
        valid_granularities = {"segment", "word"}
        self.timestamp_granularities = [
            granularity
            for granularity in (self.timestamp_granularities or [])
            if granularity in valid_granularities
        ]

        return True

    def to_request_params(self) -> dict[str, Any]:
        """
        Формирование словаря параметров для Fireworks API.

        Используем только параметры, которые точно поддерживаются библиотекой.
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

        if not self.enable_vad:
            params["skip_vad"] = True

        if self.vad_model:
            params["vad_model"] = self.vad_model

        if self.diarization:
            params["diarize"] = "speaker"
            if self.min_speakers is not None:
                params["min_speakers"] = self.min_speakers
            if self.max_speakers is not None:
                params["max_speakers"] = self.max_speakers

        if self.prompt:
            params["prompt"] = self.prompt

        if self.preprocessing:
            params["preprocessing"] = self.preprocessing

        if self.max_clip_len is not None:
            params["max_clip_len"] = self.max_clip_len

        return params


