"\"\"\"Сервис транскрибации аудио через Fireworks Audio Inference API\"\"\""

import asyncio
import os
import time
from collections import Counter
from typing import Any

try:
    from fireworks.client.audio import AudioInference
except ImportError as exc:  # pragma: no cover - среда без зависимости
    raise ImportError(
        "Не установлен пакет 'fireworks-ai'. Установите его командой "
        "`pip install fireworks-ai` или добавьте в requirements, "
        "чтобы использовать Fireworks транскрибацию."
    ) from exc

from logger import get_logger

from .config import FireworksConfig

logger = get_logger()


class FireworksTranscriptionService:
    """Асинхронная обертка над Fireworks AudioInference API."""

    def __init__(self, config: FireworksConfig):
        self.config = config
        self._client = AudioInference(
            model=self.config.model,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    async def transcribe_audio(
        self,
        audio_path: str,
        language: str | None = None,
        audio_duration: float | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Транскрибация аудио файла через Fireworks.

        Args:
            audio_path: Путь к аудио-файлу
            language: Язык аудио
            audio_duration: Известная длительность аудио (секунды) для логирования
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудио файл не найден: {audio_path}")

        params = self.config.to_request_params()
        if language:
            params["language"] = language
        if prompt:
            params["prompt"] = prompt

        retry_attempts = max(1, self.config.retry_attempts)
        retry_delay = max(0.0, self.config.retry_delay)

        with open(audio_path, "rb") as audio_file:
            audio_bytes = audio_file.read()

        last_error: Exception | None = None

        for attempt in range(1, retry_attempts + 1):
            start_time = time.time()
            try:
                logger.info(
                    f"🎆 Fireworks транскрибация (попытка {attempt}/{retry_attempts}) "
                    f"файла {os.path.basename(audio_path)}"
                )

                response = await asyncio.to_thread(
                    self._client.transcribe,
                    audio=audio_bytes,
                    **params,
                )

                elapsed = time.time() - start_time
                logger.info(
                    f"✅ Fireworks ответ получен за {elapsed/60:.1f} мин "
                    f"({elapsed:.1f} сек)"
                )

                normalized = self._normalize_response(response)
                if audio_duration:
                    ratio = (elapsed / audio_duration) if audio_duration else 0
                    logger.info(
                        f"   📊 Длительность аудио: {audio_duration/60:.1f} мин, "
                        f"коэффициент времени обработки: {ratio:.2f}x"
                    )

                return normalized

            except Exception as exc:
                last_error = exc
                elapsed = time.time() - start_time
                extra_info = self._format_error_info(exc)
                error_msg = str(exc) if not extra_info else f"{exc} | {extra_info}"
                logger.warning(
                    f"⚠️ Ошибка Fireworks транскрибации (попытка {attempt}/{retry_attempts}): {error_msg}\n"
                    f"   ⏱️  Время до ошибки: {elapsed/60:.1f} мин"
                )
                debug_params = {k: v for k, v in params.items() if k != "api_key"}
                logger.debug(f"   📋 Параметры запроса: {debug_params}")
                if attempt < retry_attempts and retry_delay > 0:
                    await asyncio.sleep(retry_delay * attempt)

        raise RuntimeError(
            f"Ошибка транскрибации через Fireworks после {retry_attempts} попыток"
        ) from last_error

    def _format_error_info(self, exc: Exception) -> str:
        """Возвращает строку со статус-кодом и телом ответа, если доступны."""
        status_code = getattr(exc, "status_code", None)
        response_obj = getattr(exc, "response", None)
        if status_code is None and response_obj is not None:
            status_code = getattr(response_obj, "status_code", None)

        response_body = ""
        if response_obj is not None:
            if getattr(response_obj, "text", None):
                response_body = response_obj.text.strip()
            elif getattr(response_obj, "content", None):
                response_body = str(response_obj.content)
        elif hasattr(exc, "body"):
            response_body = str(exc.body)

        parts: list[str] = []
        if status_code is not None:
            parts.append(f"status_code={status_code}")
        if response_body:
            max_len = 1000
            trimmed = response_body[:max_len]
            if len(response_body) > max_len:
                trimmed += "... (truncated)"
            parts.append(f"response_body={trimmed}")

        return " | ".join(parts)

    def _normalize_response(self, response: Any) -> dict[str, Any]:
        """
        Приведение ответа Fireworks к формату Whisper.

        Возвращает словарь c ключами `text`, `segments`, `language`.
        """
        if response is None:
            raise ValueError("Пустой ответ от Fireworks API")

        if hasattr(response, "model_dump"):
            payload = response.model_dump()  # Pydantic v2
        elif hasattr(response, "to_dict"):
            payload: dict[str, Any] = response.to_dict()  # type: ignore[assignment]
        elif isinstance(response, dict):
            payload = response
        else:
            payload = {}
            for key in ("text", "segments", "language", "words"):
                if hasattr(response, key):
                    payload[key] = getattr(response, key)

        text = payload.get("text") or ""
        language = payload.get("language") or self.config.language

        raw_segments: list[dict[str, Any]] = []

        if isinstance(payload.get("segments"), list):
            raw_segments = payload["segments"]
        elif isinstance(payload.get("words"), list):
            raw_segments = payload["words"]
            logger.warning(f"⚠️ Используем 'words' вместо 'segments': {len(raw_segments)} элементов")

        segments: list[dict[str, Any]] = []
        for idx, segment in enumerate(raw_segments):
            if hasattr(segment, "model_dump"):
                segment_dict = segment.model_dump()
            elif hasattr(segment, "to_dict"):
                segment_dict = segment.to_dict()
            elif isinstance(segment, dict):
                segment_dict = segment
            else:
                segment_dict = {}


            # Если в сегменте есть массив words, мы его игнорируем и используем только text сегмента
            if "words" in segment_dict and isinstance(segment_dict.get("words"), list):
                pass

            start = segment_dict.get("start") or segment_dict.get("start_time") or segment_dict.get("offset")
            end = segment_dict.get("end") or segment_dict.get("end_time") or segment_dict.get("offset_end")
            seg_text = segment_dict.get("text") or segment_dict.get("word") or ""

            # Fireworks всегда возвращает время в секундах, конвертируем в float
            start_float = float(start) if isinstance(start, (int, float)) else 0.0
            end_float = float(end) if isinstance(end, (int, float)) else 0.0

            # Исправляем сегменты с нулевой длительностью
            # Если end <= start, устанавливаем минимальную длительность 0.1 секунды
            if end_float <= start_float:
                end_float = start_float + 0.1

            # Пропускаем пустые сегменты (без текста)
            if not seg_text.strip():
                continue

            segments.append(
                {
                    "id": segment_dict.get("id", idx),
                    "start": start_float,
                    "end": end_float,
                    "text": seg_text.strip(),
                }
            )

        # Проверяем на дубликаты временных меток
        if segments:
            start_times = [seg["start"] for seg in segments]
            time_counts = Counter(start_times)
            duplicates = {time: count for time, count in time_counts.items() if count > 1}
            if duplicates:
                logger.warning(
                    f"⚠️ Найдены сегменты с одинаковыми временными метками: {len(duplicates)} уникальных времен, "
                    f"максимум дубликатов: {max(duplicates.values())} сегментов на время {max(duplicates.items(), key=lambda x: x[1])[0]:.2f}с"
                )

        # Сортируем сегменты по времени начала (на случай, если порядок нарушен)
        segments.sort(key=lambda x: x.get("start", 0))

        return {
            "text": text,
            "segments": segments,
            "language": language,
        }


