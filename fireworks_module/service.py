'"""Сервис транскрибации аудио через Fireworks Audio Inference API"""'

import asyncio
import json
import os
import re
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

try:
    import httpx
except ImportError as exc:  # pragma: no cover - среда без зависимости
    raise ImportError(
        "Не установлен пакет 'httpx'. Установите его командой "
        "`pip install httpx` для использования Batch API."
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

        # Логируем используемую модель и параметры запроса (без api_key)
        debug_payload = self._build_request_log(params, audio_path)
        logger.debug(f"Fireworks | Request | {debug_payload}")

        retry_attempts = max(1, self.config.retry_attempts)
        base_delay = max(0.0, self.config.retry_delay)
        max_delay = 60.0  # Максимальная задержка 60 секунд

        with open(audio_path, "rb") as audio_file:
            audio_bytes = audio_file.read()

        last_error: Exception | None = None

        for attempt in range(1, retry_attempts + 1):
            start_time = time.time()
            try:
                logger.info(
                    "Fireworks | Attempt {attempt}/{total} | model={model} | file={file}",
                    attempt=attempt,
                    total=retry_attempts,
                    model=self.config.model,
                    file=os.path.basename(audio_path),
                )

                response = await asyncio.to_thread(
                    self._client.transcribe,
                    audio=audio_bytes,
                    **params,
                )

                elapsed = time.time() - start_time
                logger.info(
                    "Fireworks | Success | model={model} | elapsed={elapsed:.1f}s ({minutes:.1f} min)",
                    model=self.config.model,
                    elapsed=elapsed,
                    minutes=elapsed / 60,
                )

                # Логируем сырой ответ от Fireworks для отладки
                self._log_raw_response(response)

                # Если формат ответа SRT или VTT, обрабатываем как строку
                if self.config.response_format in ("srt", "vtt"):
                    normalized = self._normalize_srt_response(response)
                else:
                    normalized = self._normalize_response(response)
                if audio_duration:
                    ratio = (elapsed / audio_duration) if audio_duration else 0
                    logger.info(
                        "Fireworks | Speed | audio={audio_min:.1f} min | proc_ratio={ratio:.2f}x",
                        audio_min=audio_duration / 60,
                        ratio=ratio,
                    )

                return normalized

            except Exception as exc:
                last_error = exc
                elapsed = time.time() - start_time
                extra_info = self._format_error_info(exc)
                error_msg = str(exc) if not extra_info else f"{exc} | {extra_info}"
                logger.warning(
                    "Fireworks | Error | model={model} | attempt={attempt}/{total} | elapsed={elapsed:.1f}s | {error}",
                    model=self.config.model,
                    attempt=attempt,
                    total=retry_attempts,
                    elapsed=elapsed,
                    error=error_msg,
                )
                debug_payload = self._build_request_log(params, audio_path)
                logger.debug(f"Fireworks | Request | {debug_payload}")

                # Экспоненциальная задержка: base_delay * (2 ** attempt_index)
                # attempt_index = 0 для первой повторной попытки, 1 для второй и т.д.
                if attempt < retry_attempts and base_delay > 0:
                    attempt_index = attempt - 1  # Индекс для экспоненциальной задержки
                    delay = min(base_delay * (2**attempt_index), max_delay)
                    logger.info(
                        "Fireworks | Retry in {delay:.1f}s | next attempt {next_attempt}/{total}",
                        delay=delay,
                        next_attempt=attempt + 1,
                        total=retry_attempts,
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError(f"Ошибка транскрибации через Fireworks после {retry_attempts} попыток") from last_error

    def _build_request_log(self, params: dict[str, Any], audio_path: str) -> dict[str, Any]:
        """Единообразное тело для логирования параметров запроса."""
        safe_params = {k: v for k, v in params.items() if k != "api_key"}
        return {
            "model": self.config.model,
            "base_url": self.config.base_url,
            "file": os.path.basename(audio_path),
            **safe_params,
        }

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

    def _log_raw_response(self, response: Any) -> None:
        """Логирует сырой ответ от Fireworks для отладки."""
        try:
            if hasattr(response, "model_dump"):
                payload = response.model_dump()
            elif hasattr(response, "to_dict"):
                payload = response.to_dict()
            elif isinstance(response, dict):
                payload = response
            else:
                logger.debug("Сырой ответ Fireworks: объект без стандартных методов сериализации")
                return

            logger.debug(f"Структура ответа Fireworks: keys={list(payload.keys())}")

            words = payload.get("words", [])
            if isinstance(words, list) and len(words) > 0:
                logger.debug(f"Первые 10 words из ответа Fireworks: count={len(words)}")
                for i, word in enumerate(words[:10]):
                    if hasattr(word, "model_dump"):
                        word_dict = word.model_dump()
                    elif hasattr(word, "to_dict"):
                        word_dict = word.to_dict()
                    elif isinstance(word, dict):
                        word_dict = word
                    else:
                        continue

                    word_text = word_dict.get("word") or word_dict.get("text") or ""
                    word_start = word_dict.get("start") or word_dict.get("start_time") or word_dict.get("offset")
                    word_end = word_dict.get("end") or word_dict.get("end_time") or word_dict.get("offset_end")
                    duration = float(word_end) - float(word_start) if word_start and word_end else 0.0

                    logger.debug(
                        f"Word [{i + 1}]: text='{word_text}' | start={word_start} | end={word_end} | duration={duration:.3f}s"
                    )

            segments = payload.get("segments", [])
            if isinstance(segments, list) and len(segments) > 0:
                logger.debug(f"Первые 5 segments из ответа Fireworks: total={len(segments)}")
                for i, seg in enumerate(segments[:5]):
                    if hasattr(seg, "model_dump"):
                        seg_dict = seg.model_dump()
                    elif hasattr(seg, "to_dict"):
                        seg_dict = seg.to_dict()
                    elif isinstance(seg, dict):
                        seg_dict = seg
                    else:
                        continue

                    seg_text = seg_dict.get("text") or ""
                    seg_start = seg_dict.get("start") or seg_dict.get("start_time") or seg_dict.get("offset")
                    seg_end = seg_dict.get("end") or seg_dict.get("end_time") or seg_dict.get("offset_end")
                    duration = float(seg_end) - float(seg_start) if seg_start and seg_end else 0.0

                    logger.info(
                        f"   [{i + 1}] '{seg_text[:50]}...': start={seg_start}, end={seg_end}, duration={duration:.3f}с"
                    )

        except Exception as e:
            logger.warning(f"⚠️ Не удалось залогировать сырой ответ Fireworks: {e}")

    def _create_segments_from_words(
        self,
        words: list[dict[str, Any]],
        max_duration_seconds: float = 8.0,
        pause_threshold_seconds: float = 0.4,
    ) -> list[dict[str, Any]]:
        """
        Создает сегменты из слов с максимальной точностью синхронизации.

        Приоритеты разбиения (в порядке важности):
        1. Конец предложения (., !, ?) - всегда разбивать
        2. Пауза > pause_threshold_seconds - обязательная граница (если в группе уже есть «достаточно» слов)
        3. Запятая + пауза > 0.25 сек - разбивать на части предложения (если в группе уже есть «достаточно» слов)
        4. Превышение max_duration_seconds - принудительное разбиение (если в группе уже есть «достаточно» слов)

        Args:
            words: Список словарей с ключами 'start', 'end', 'word'
            max_duration_seconds: Максимальная длительность сегмента в секундах (по умолчанию 5.0)
            pause_threshold_seconds: Порог паузы для начала нового сегмента в секундах (по умолчанию 0.3)

        Returns:
            Список сегментов с ключами 'id', 'start', 'end', 'text'
        """
        if not words:
            return []

        # Знаки препинания
        sentence_endings = (".", "!", "?", "…")  # Конец предложения - высший приоритет
        comma_punctuation = (",",)  # Запятая - средний приоритет (с паузой)
        pause_for_comma = 0.25  # Минимальная пауза для разбиения по запятой

        # Хард-стопы/минимумы
        min_group_duration_for_pause_break = 0.7  # Минимальная длительность группы для разбиения по паузам/запятым
        min_words_for_break = 3  # Минимум слов в группе, чтобы разрешать разбиение по паузам/запятым/длине

        # Порог для дальнейшего слияния очень коротких сегментов
        short_segment_duration = 1.2
        short_segment_words = 3

        segments: list[dict[str, Any]] = []
        current_group: list[dict[str, Any]] = []
        current_start: float | None = None
        segment_id = 0

        def _finalize_segment(group: list[dict[str, Any]], start: float) -> dict[str, Any] | None:
            """Создает сегмент из группы слов с точными временными метками."""
            if not group or start is None:
                return None

            group_text = " ".join(w.get("word", "").strip() for w in group)
            if not group_text.strip():
                return None

            # Используем точные временные метки: начало первого слова, конец последнего слова
            group_start = start
            last_word_end_raw = group[-1].get("end", 0.0)
            group_end = float(last_word_end_raw) if isinstance(last_word_end_raw, (int, float)) else 0.0

            # Защита от некорректных временных меток
            if group_end <= group_start:
                group_end = group_start + 0.1

            return {
                "id": segment_id,
                "start": group_start,
                "end": group_end,
                "text": group_text.strip(),
            }

        for _, word_item in enumerate(words):
            word_start = word_item.get("start", 0.0)
            word_end = word_item.get("end", 0.0)
            word_text = word_item.get("word", "").strip()

            if not word_text:
                continue

            # Валидация и нормализация временных меток слова
            word_start_float = float(word_start) if isinstance(word_start, (int, float)) else 0.0
            word_end_float = float(word_end) if isinstance(word_end, (int, float)) else 0.0

            # Исправляем слова с некорректными временными метками
            if word_end_float <= word_start_float:
                word_end_float = word_start_float + 0.1

            # Обновляем word_item с нормализованными значениями
            word_item = {**word_item, "start": word_start_float, "end": word_end_float}

            # Определяем начало группы
            if current_start is None:
                current_start = word_start_float

            # Вычисляем паузу перед текущим словом
            pause_duration = 0.0
            if current_group:
                last_word_end = current_group[-1].get("end", 0.0)
                last_word_end_float = float(last_word_end) if isinstance(last_word_end, (int, float)) else 0.0
                pause_duration = word_start_float - last_word_end_float

            # Проверяем, заканчивается ли слово на знак препинания
            # Используем кортежи для проверки (endswith принимает кортеж)
            ends_with_sentence = word_text.endswith(sentence_endings)
            ends_with_comma = word_text.endswith(comma_punctuation)

            # ПРИОРИТЕТ 1: Конец предложения - всегда разбивать (даже без паузы)
            should_break_sentence = ends_with_sentence

            # ПРИОРИТЕТ 2: Пауза больше порога - обязательная граница
            # НО: не разбиваем по паузам, если текущая группа слишком короткая (< 0.5 сек)
            # Это предотвращает разбиение на отдельные слова из-за больших пауз
            current_group_duration = (
                (current_group[-1].get("end", 0.0) - current_start)
                if current_group and current_start is not None
                else 0.0
            )
            enough_group = (
                current_group_duration >= min_group_duration_for_pause_break
                or len(current_group) >= min_words_for_break
            )

            should_break_pause = pause_duration > pause_threshold_seconds and enough_group

            # ПРИОРИТЕТ 3: Запятая + пауза > 0.2 сек - разбивать на части предложения
            # Для запятой тоже учитываем минимальную длительность группы
            should_break_comma = ends_with_comma and pause_duration > pause_for_comma and enough_group

            # ПРИОРИТЕТ 4: Превышение максимальной длительности
            # Вычисляем длительность группы ПОСЛЕ добавления текущего слова
            group_duration_after = word_end_float - current_start
            should_break_duration = group_duration_after > max_duration_seconds and enough_group

            # Определяем, нужно ли разбивать сегмент
            # Для конца предложения - разбиваем ПОСЛЕ добавления слова (высший приоритет)
            # Для остальных случаев - разбиваем ДО добавления слова
            should_break_before = (
                should_break_pause or should_break_comma or should_break_duration
            ) and not should_break_sentence

            # Если нужно разбить ДО добавления слова (пауза, запятая, длительность)
            # Но НЕ если это конец предложения (для него приоритет - разбивать ПОСЛЕ)
            if should_break_before and current_group and current_start is not None:
                segment = _finalize_segment(current_group, current_start)
                if segment:
                    segments.append(segment)
                    segment_id += 1

                # Начинаем новую группу
                current_group = []
                current_start = word_start_float

            # Добавляем слово в текущую группу
            current_group.append(word_item)

            # Если это конец предложения, сразу завершаем группу (после добавления слова)
            # Это высший приоритет - всегда разбиваем по предложениям
            if should_break_sentence and current_group and current_start is not None:
                segment = _finalize_segment(current_group, current_start)
                if segment:
                    segments.append(segment)
                    segment_id += 1

                # Начинаем новую группу
                current_group = []
                current_start = None

        # Добавляем последнюю группу
        if current_group and current_start is not None:
            segment = _finalize_segment(current_group, current_start)
            if segment:
                segments.append(segment)

        # После первичного построения — постобъединение слишком коротких сегментов
        if not segments:
            return segments

        merged: list[dict[str, Any]] = []

        def seg_word_count(seg: dict[str, Any]) -> int:
            return len(seg.get("text", "").split())

        for seg in segments:
            if (
                seg_word_count(seg) < short_segment_words
                and (seg.get("end", 0.0) - seg.get("start", 0.0)) < short_segment_duration
                and merged
            ):
                # Сливаем с предыдущим сегментом для улучшения читабельности
                prev = merged.pop()
                merged_seg = {
                    "id": prev["id"],
                    "start": prev["start"],
                    "end": seg["end"],
                    "text": f"{prev['text']} {seg['text']}".strip(),
                }
                merged.append(merged_seg)
            else:
                merged.append(seg)

        # Перенумеровываем id после слияния
        for idx, seg in enumerate(merged):
            seg["id"] = idx

        return merged

    def _normalize_response(self, response: Any) -> dict[str, Any]:
        """
        Приведение ответа Fireworks к формату Whisper.

        Возвращает словарь c ключами `text`, `segments`, `words`, `language`.
        Сегменты создаются локально из words с группировкой по предложениям и паузам.
        Требует, чтобы timestamp_granularities содержал 'word' в конфигурации Fireworks.
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

        # Segments от Fireworks (используем напрямую, если есть)
        raw_segments = payload.get("segments", [])
        segments_from_api: list[dict[str, Any]] = []
        if isinstance(raw_segments, list) and len(raw_segments) > 0:
            logger.debug(f"🔍 В ответе Fireworks найдено {len(raw_segments)} segments (API)")
            for seg_item in raw_segments:
                if hasattr(seg_item, "model_dump"):
                    seg_dict = seg_item.model_dump()
                elif hasattr(seg_item, "to_dict"):
                    seg_dict = seg_item.to_dict()
                elif isinstance(seg_item, dict):
                    seg_dict = seg_item
                else:
                    continue

                seg_text = seg_dict.get("text") or seg_dict.get("segment") or ""
                seg_start = seg_dict.get("start") or seg_dict.get("start_time") or seg_dict.get("offset")
                seg_end = seg_dict.get("end") or seg_dict.get("end_time") or seg_dict.get("offset_end")

                if not seg_text.strip():
                    continue

                seg_start_float = float(seg_start) if isinstance(seg_start, (int, float)) else 0.0
                seg_end_float = float(seg_end) if isinstance(seg_end, (int, float)) else 0.0
                if seg_end_float <= seg_start_float:
                    seg_end_float = seg_start_float + 0.1

                segments_from_api.append(
                    {
                        "id": len(segments_from_api),
                        "start": seg_start_float,
                        "end": seg_end_float,
                        "text": seg_text.strip(),
                    }
                )

            logger.info(f"📥 Получено {len(segments_from_api)} сегментов из Fireworks API")
        else:
            logger.info("ℹ️ Segments отсутствуют в ответе Fireworks, будем строить их локально из words")

        # Извлекаем words из payload
        all_words: list[dict[str, Any]] = []
        raw_words: list[dict[str, Any]] = []

        # Получаем words напрямую из payload
        if isinstance(payload.get("words"), list):
            raw_words = payload["words"]

            # DEBUG: Логируем первые 10 words с ПОЛНОЙ структурой от Fireworks для диагностики (только в DEBUG режиме)
            logger.debug(f"Первые 10 words с полной структурой от Fireworks: total={len(raw_words)}")
            for i, word_item in enumerate(raw_words[:10]):
                if hasattr(word_item, "model_dump"):
                    word_dict = word_item.model_dump()
                elif hasattr(word_item, "to_dict"):
                    word_dict = word_item.to_dict()
                elif isinstance(word_item, dict):
                    word_dict = word_item
                else:
                    continue

                # Логируем ВСЕ поля слова для диагностики
                logger.debug(f"Word [{i + 1}] полная структура: {word_dict}")

                word_start = word_dict.get("start") or word_dict.get("start_time") or word_dict.get("offset")
                word_end = word_dict.get("end") or word_dict.get("end_time") or word_dict.get("offset_end")
                word_text = word_dict.get("word") or word_dict.get("text") or ""

                logger.debug(
                    f"Word [{i + 1}]: text='{word_text}' | start={word_start} | end={word_end} | "
                    f"duration={float(word_end) - float(word_start) if word_start and word_end else 0.0:.3f}s"
                )
        else:
            logger.warning(
                "⚠️ Words не найдены в ответе Fireworks. Убедитесь, что timestamp_granularities содержит 'word'."
            )

        # Обрабатываем words
        word_id = 0
        for word_item in raw_words:
            if hasattr(word_item, "model_dump"):
                word_dict = word_item.model_dump()
            elif hasattr(word_item, "to_dict"):
                word_dict = word_item.to_dict()
            elif isinstance(word_item, dict):
                word_dict = word_item
            else:
                continue

            word_start = word_dict.get("start") or word_dict.get("start_time") or word_dict.get("offset")
            word_end = word_dict.get("end") or word_dict.get("end_time") or word_dict.get("offset_end")
            word_text = word_dict.get("word") or word_dict.get("text") or ""

            if not word_text.strip():
                continue

            word_start_float = float(word_start) if isinstance(word_start, (int, float)) else 0.0
            word_end_float = float(word_end) if isinstance(word_end, (int, float)) else 0.0

            # Исправляем слова с нулевой длительностью
            if word_end_float <= word_start_float:
                word_end_float = word_start_float + 0.1

            # Проверяем на аномально длинные слова (больше 3 секунд - подозрительно)
            word_duration = word_end_float - word_start_float
            if word_duration > 3.0:
                logger.warning(
                    f"⚠️ Обнаружено аномально длинное слово '{word_text}': "
                    f"start={word_start_float:.3f}с, end={word_end_float:.3f}с, "
                    f"длительность={word_duration:.3f}с"
                )
                # Исправляем: устанавливаем длительность слова на основе средней длительности
                # или используем время следующего слова, если оно есть
                # Пока оставляем как есть, но логируем для анализа

            all_words.append(
                {
                    "id": word_id,
                    "start": word_start_float,
                    "end": word_end_float,
                    "word": word_text.strip(),
                }
            )
            word_id += 1

        # Сортируем words по времени начала
        all_words.sort(key=lambda x: x.get("start", 0))

        # Анализируем words на аномалии
        if all_words:
            durations = [w.get("end", 0) - w.get("start", 0) for w in all_words]
            avg_duration = sum(durations) / len(durations) if durations else 0.0
            max_duration = max(durations) if durations else 0.0
            long_words = [w for w in all_words if (w.get("end", 0) - w.get("start", 0)) > 3.0]

            logger.info(
                f"📊 Статистика words: всего={len(all_words)}, "
                f"средняя длительность={avg_duration:.3f}с, "
                f"максимальная длительность={max_duration:.3f}с, "
                f"аномально длинных (>3с)={len(long_words)}"
            )

            if long_words:
                logger.warning("⚠️ Аномально длинные слова (>3 секунд):")
                for w in long_words[:10]:  # Показываем первые 10
                    duration = w.get("end", 0) - w.get("start", 0)
                    logger.warning(
                        f"   '{w.get('word', '')}': "
                        f"{w.get('start', 0):.3f}с - {w.get('end', 0):.3f}с "
                        f"(длительность={duration:.3f}с)"
                    )

        # Сегменты из слов (наше группирование) для совместимости
        segments_auto: list[dict[str, Any]] = []
        if all_words:
            logger.info(f"🔄 Создание сегментов из {len(all_words)} слов (локально)...")
            segments_auto = self._create_segments_from_words(all_words)
            logger.info(f"✅ Создано {len(segments_auto)} сегментов локально")
        else:
            logger.error(
                "❌ Не удалось создать сегменты: words отсутствуют. "
                "Проверьте конфигурацию Fireworks (timestamp_granularities должен содержать 'word')."
            )
            raise ValueError(
                "Не удалось извлечь words из ответа Fireworks. "
                "Убедитесь, что timestamp_granularities содержит 'word' в конфигурации."
            )

        # Определяем финальный набор сегментов (API приоритетен, fallback — локальные)
        final_segments = segments_from_api if segments_from_api else segments_auto

        # Проверяем на дубликаты временных меток в финальных сегментах
        if final_segments:
            start_times = [seg["start"] for seg in final_segments]
            time_counts = Counter(start_times)
            duplicates = {time: count for time, count in time_counts.items() if count > 1}
            if duplicates:
                logger.warning(
                    f"⚠️ Найдены сегменты с одинаковыми временными метками: {len(duplicates)} уникальных времен, "
                    f"максимум дубликатов: {max(duplicates.values())} сегментов на время {max(duplicates.items(), key=lambda x: x[1])[0]:.2f}с"
                )

        # Сортируем сегменты по времени начала
        final_segments.sort(key=lambda x: x.get("start", 0))

        logger.info(
            f"📊 Итог: {len(final_segments)} сегментов (API приоритет), {len(all_words)} слов. "
            f"Локальные сегменты сохранены как резерв."
        )

        return {
            "text": text,
            "segments": final_segments,
            "segments_auto": segments_auto,
            "words": all_words,
            "language": language,
        }

    def _parse_srt_time(self, time_str: str) -> float:
        """
        Парсит время из формата SRT (HH:MM:SS,mmm) в секунды.

        Args:
            time_str: Строка времени в формате HH:MM:SS,mmm или HH:MM:SS.mmm

        Returns:
            Время в секундах (float)
        """
        # Поддерживаем оба формата: запятая (SRT) и точка (VTT)
        time_str = time_str.replace(",", ".")

        parts = time_str.split(":")
        if len(parts) != 3:
            return 0.0

        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split(".")
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0

        total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
        return total_seconds

    def _normalize_srt_response(self, response: Any) -> dict[str, Any]:
        """
        Парсит ответ Fireworks в формате SRT/VTT и преобразует в стандартный формат.

        Args:
            response: Ответ от Fireworks API (может быть строкой или объектом)

        Returns:
            Словарь c ключами `text`, `segments`, `language`, `srt_content`.
        """
        if response is None:
            raise ValueError("Пустой ответ от Fireworks API")

        # Извлекаем строку SRT из ответа
        srt_content = ""
        if isinstance(response, str):
            srt_content = response
        elif hasattr(response, "text"):
            srt_content = response.text
        elif isinstance(response, dict):
            srt_content = response.get("text", "") or response.get("content", "")
        elif hasattr(response, "model_dump"):
            payload = response.model_dump()
            srt_content = payload.get("text", "") or payload.get("content", "")
        elif hasattr(response, "to_dict"):
            payload = response.to_dict()
            srt_content = payload.get("text", "") or payload.get("content", "")

        if not srt_content:
            raise ValueError("Не удалось извлечь SRT контент из ответа Fireworks")

        logger.info(f"📝 Парсинг SRT ответа от Fireworks ({len(srt_content)} символов)")

        # Парсим SRT формат
        # Формат SRT:
        # 1
        # 00:00:06,408 --> 00:00:07,027
        # Текст субтитра
        # (пустая строка)

        segments: list[dict[str, Any]] = []
        full_text_parts: list[str] = []

        # Регулярное выражение для временной метки SRT: HH:MM:SS,mmm --> HH:MM:SS,mmm
        timestamp_pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")

        lines = srt_content.split("\n")
        i = 0
        segment_id = 0

        while i < len(lines):
            line = lines[i].strip()

            # Пропускаем пустые строки и номер субтитра
            if not line or line.isdigit():
                i += 1
                continue

            # Проверяем, является ли строка временной меткой
            match = timestamp_pattern.match(line)
            if match:
                # Извлекаем временные метки
                start_time_str = f"{match.group(1)}:{match.group(2)}:{match.group(3)}.{match.group(4)}"
                end_time_str = f"{match.group(5)}:{match.group(6)}:{match.group(7)}.{match.group(8)}"

                start_seconds = self._parse_srt_time(start_time_str)
                end_seconds = self._parse_srt_time(end_time_str)

                # Собираем текст субтитра (может быть несколько строк)
                i += 1
                subtitle_lines = []
                while i < len(lines) and lines[i].strip():
                    subtitle_lines.append(lines[i].strip())
                    i += 1

                subtitle_text = " ".join(subtitle_lines).strip()

                if subtitle_text:
                    segments.append(
                        {
                            "id": segment_id,
                            "start": start_seconds,
                            "end": end_seconds,
                            "text": subtitle_text,
                        }
                    )
                    full_text_parts.append(subtitle_text)
                    segment_id += 1
            else:
                i += 1

        # Формируем полный текст
        full_text = " ".join(full_text_parts)
        language = self.config.language

        logger.info(f"✅ SRT парсинг завершен: {len(full_text)} символов, {len(segments)} сегментов из SRT")

        return {
            "text": full_text,
            "segments": segments,
            "words": [],  # В SRT формате нет информации о словах
            "language": language,
            "srt_content": srt_content,  # Сохраняем оригинальный SRT контент
        }

    # ==================== Batch API Methods ====================

    async def submit_batch_transcription(
        self,
        audio_path: str,
        language: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Отправляет аудио на транскрибацию через Fireworks Batch API.

        Batch API дешевле синхронного, но требует polling для получения результата.
        Документация: https://docs.fireworks.ai/api-reference/create-batch-request

        Args:
            audio_path: Путь к аудио-файлу
            language: Язык аудио
            prompt: Промпт для улучшения качества

        Returns:
            Dict с batch_id и метаданными:
            {
                "batch_id": "...",
                "status": "submitted",
                "account_id": "...",
                "endpoint_id": "...",
                "message": "..."
            }

        Raises:
            ValueError: Если account_id не настроен
            FileNotFoundError: Если файл не найден
        """
        if not self.config.account_id:
            raise ValueError(
                "account_id не настроен. Добавьте account_id в config/fireworks_creds.json "
                "для использования Batch API (найти в Fireworks dashboard)."
            )

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудио файл не найден: {audio_path}")

        # Определяем endpoint_id на основе модели
        endpoint_id = "audio-turbo" if self.config.model == "whisper-v3-turbo" else "audio-prod"

        # Формируем параметры запроса (аналогично синхронному API)
        params = self.config.to_request_params()
        if language:
            params["language"] = language
        if prompt:
            params["prompt"] = prompt

        # Batch API URL
        url = f"{self.config.batch_base_url}/v1/audio/transcriptions"

        logger.info(
            f"Fireworks Batch | Submitting | endpoint={endpoint_id} | file={os.path.basename(audio_path)} | model={self.config.model}"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(audio_path, "rb") as audio_file:
                files = {"file": (os.path.basename(audio_path), audio_file, "audio/mpeg")}

                # Batch API требует параметры в формате multipart/form-data
                # Документация требует JSON-сериализацию параметров
                data = {key: json.dumps(value) if not isinstance(value, str) else value for key, value in params.items()}

                response = await client.post(
                    url,
                    params={"endpoint_id": endpoint_id},
                    headers={"Authorization": self.config.api_key},
                    files=files,
                    data=data,
                )

                if response.status_code != 200:
                    error_text = response.text
                    logger.error(
                        f"Fireworks Batch | Submit Error | status={response.status_code} | error={error_text[:500]}"
                    )
                    raise RuntimeError(
                        f"Ошибка отправки в Batch API: {response.status_code} - {error_text[:200]}"
                    )

                result = response.json()
                logger.info(
                    f"Fireworks Batch | Submitted ✅ | batch_id={result.get('batch_id')} | status={result.get('status')}"
                )
                return result

    async def check_batch_status(self, batch_id: str) -> dict[str, Any]:
        """
        Проверяет статус batch job.

        Документация: https://docs.fireworks.ai/api-reference/get-batch-status

        Args:
            batch_id: ID batch job (из submit_batch_transcription)

        Returns:
            Dict со статусом:
            {
                "status": "processing" | "completed",
                "batch_id": "...",
                "message": None,
                "content_type": "application/json",  # если completed
                "body": "..."  # если completed
            }
        """
        if not self.config.account_id:
            raise ValueError("account_id не настроен для Batch API")

        url = f"{self.config.batch_base_url}/v1/accounts/{self.config.account_id}/batch_job/{batch_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": self.config.api_key},
            )

            if response.status_code != 200:
                error_text = response.text
                logger.error(
                    f"Fireworks Batch | Status Check Error | batch_id={batch_id} | status={response.status_code} | error={error_text[:500]}"
                )
                raise RuntimeError(
                    f"Ошибка проверки статуса Batch API: {response.status_code} - {error_text[:200]}"
                )

            result = response.json()
            status = result.get("status", "unknown")
            logger.debug(f"Fireworks Batch | Status Check | batch_id={batch_id} | status={status}")
            return result

    async def get_batch_result(self, batch_id: str) -> dict[str, Any]:
        """
        Получает результат batch job (только для completed jobs).

        Args:
            batch_id: ID batch job

        Returns:
            Normalized результат (аналогично transcribe_audio)

        Raises:
            RuntimeError: Если job еще не завершен
        """
        status_response = await self.check_batch_status(batch_id)

        if status_response.get("status") != "completed":
            raise RuntimeError(
                f"Batch job {batch_id} еще не завершен. Статус: {status_response.get('status')}"
            )

        # Парсим body (содержит результат транскрибации)
        body_str = status_response.get("body")
        if not body_str:
            raise RuntimeError(f"Batch job {batch_id} не содержит результата (body пустой)")

        content_type = status_response.get("content_type", "application/json")

        # Парсим результат в зависимости от content_type
        if "json" in content_type:
            result = json.loads(body_str)
            # Normalize как обычный response
            return self._normalize_response(result)
        elif "srt" in content_type or "vtt" in content_type:
            # SRT/VTT формат
            return self._normalize_srt_response(body_str)
        else:
            # Fallback - пробуем JSON
            try:
                result = json.loads(body_str)
                return self._normalize_response(result)
            except json.JSONDecodeError:
                # Пробуем как текст
                return {
                    "text": body_str,
                    "segments": [],
                    "words": [],
                    "language": self.config.language,
                }

    async def wait_for_batch_completion(
        self,
        batch_id: str,
        poll_interval: float = 10.0,
        max_wait_time: float = 3600.0,
    ) -> dict[str, Any]:
        """
        Ожидает завершения batch job с polling.

        Args:
            batch_id: ID batch job
            poll_interval: Интервал проверки в секундах
            max_wait_time: Максимальное время ожидания в секундах

        Returns:
            Результат транскрибации (normalized)

        Raises:
            TimeoutError: Если превышено max_wait_time
        """
        start_time = time.time()
        attempt = 0

        logger.info(
            f"Fireworks Batch | Waiting for completion | batch_id={batch_id} | poll_interval={poll_interval}s"
        )

        while True:
            attempt += 1
            elapsed = time.time() - start_time

            if elapsed > max_wait_time:
                raise TimeoutError(
                    f"Batch job {batch_id} не завершился за {max_wait_time}s (попыток: {attempt})"
                )

            status_response = await self.check_batch_status(batch_id)
            status = status_response.get("status", "unknown")

            if status == "completed":
                logger.info(
                    f"Fireworks Batch | Completed ✅ | batch_id={batch_id} | elapsed={elapsed:.1f}s | attempts={attempt}"
                )
                return await self.get_batch_result(batch_id)

            logger.debug(
                f"Fireworks Batch | Polling | batch_id={batch_id} | status={status} | attempt={attempt} | elapsed={elapsed:.1f}s"
            )

            await asyncio.sleep(poll_interval)
