"""Извлечение тем из транскрипции через DeepSeek"""

import re
from typing import Any

from openai import AsyncOpenAI

from logger import format_log, get_logger

from .config import DeepSeekConfig

logger = get_logger(__name__)


class TopicExtractor:
    """Извлечение тем из транскрипции используя MapReduce подход"""

    def __init__(self, config: DeepSeekConfig):
        self.config = config

        if "deepseek.com" not in config.base_url.lower():
            raise ValueError(
                f"❌ ОШИБКА: Указан не DeepSeek endpoint! "
                f"Получен: {config.base_url}, ожидается: https://api.deepseek.com/v1"
            )

        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        logger.info(
            format_log(
                "TopicExtractor инициализирован",
                базовый_url=config.base_url,
                модель=config.model,
            )
        )

    async def extract_topics(
        self,
        transcription_text: str,
        segments: list[dict] | None = None,
        recording_topic: str | None = None,
        granularity: str = "long",  # "short" | "long"
    ) -> dict[str, Any]:
        """
        Извлечение тем из транскрипции через DeepSeek.

        Args:
            transcription_text: Полный текст транскрипции
            segments: Список сегментов с временными метками (обязательно)
            recording_topic: Название курса/предмета для контекста (опционально)

        Returns:
            Словарь с темами:
            {
                'topic_timestamps': [
                    {'topic': str, 'start': float, 'end': float},
                    ...
                ],
                'main_topics': [str, ...]  # Максимум 2 темы
                'long_pauses': [
                    {'start': float, 'end': float, 'duration_minutes': float},
                    ...
                ]  # Паузы >=8 минут между сегментами
            }
        """
        if not segments or len(segments) == 0:
            raise ValueError("Сегменты обязательны для извлечения тем")

        logger.info(
            format_log(
                "Извлекаем темы из транскрипта",
                количество_сегментов=len(segments),
            )
        )
        if recording_topic:
            logger.info(
                format_log(
                    "Используем контекст записи",
                    тема_записи=recording_topic,
                )
            )

        total_duration = segments[-1].get('end', 0) if segments else 0
        duration_minutes = total_duration / 60
        logger.info(
            format_log(
                "Рассчитана длительность видео",
                длительность_минут=round(duration_minutes, 1),
            )
        )

        min_topics, max_topics = self._calculate_topic_range(duration_minutes, granularity=granularity)
        logger.info(
            format_log(
                "Рассчитан диапазон количества тем",
                минимум_тем=min_topics,
                максимум_тем=max_topics,
                длительность_минут=round(duration_minutes, 1),
            )
        )

        transcript_with_timestamps = self._format_transcript_with_timestamps(segments)
        try:
            result = await self._analyze_full_transcript(
                transcript_with_timestamps,
                total_duration,
                recording_topic,
                min_topics,
                max_topics,
                granularity=granularity,
                segments=segments,
            )

            main_topics = result.get('main_topics', [])
            topic_timestamps = result.get('topic_timestamps', [])

            topic_timestamps_with_end = self._add_end_timestamps(topic_timestamps, total_duration)

            logger.info(
                format_log(
                    "Темы успешно извлечены",
                    количество_основных=len(main_topics),
                    количество_детализированных=len(topic_timestamps_with_end),
                )
            )

            return {
                'topic_timestamps': topic_timestamps_with_end,
                'main_topics': main_topics,
                'long_pauses': result.get('long_pauses', []),
            }
        except Exception as error:
            logger.exception(
                format_log(
                    "Не удалось извлечь темы",
                    ошибка=str(error),
                )
            )
            return {
                'topic_timestamps': [],
                'main_topics': [],
            }

    def _format_transcript_with_timestamps(self, segments: list[dict]) -> str:
        """
        Форматирование транскрипции с временными метками.

        Args:
            segments: Список сегментов с временными метками

        Returns:
            Отформатированная транскрипция
        """
        segments_text = []
        noise_patterns = [
            r"редактор субтитров",
            r"корректор",
            r"продолжение следует",
        ]
        # Оцениваем, есть ли длинное окно шума (15+ минут подряд)
        noise_times = []
        for seg in segments:
            text0 = (seg.get('text') or '').strip().lower()
            if text0 and any(re.search(pat, text0) for pat in noise_patterns):
                try:
                    noise_times.append(float(seg.get('start', 0)))
                except Exception:
                    pass
        exclude_from = None
        exclude_to = None
        if noise_times:
            first_noise = min(noise_times)
            last_noise = max(noise_times)
            if (last_noise - first_noise) >= 15 * 60:
                exclude_from, exclude_to = first_noise, last_noise

        for seg in segments:
            start = seg.get('start', 0)
            text = seg.get('text', '').strip()
            if text:
                lowered = text.lower()
                # Пропускаем шумовые строки
                if any(re.search(pat, lowered) for pat in noise_patterns):
                    continue
                # Пропускаем всё, что попало в длинное окно шума
                if exclude_from is not None and exclude_to is not None:
                    try:
                        if exclude_from <= float(start) <= exclude_to:
                            continue
                    except Exception:
                        pass
                hours = int(start // 3600)
                minutes = int((start % 3600) // 60)
                seconds = int(start % 60)
                time_str = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
                segments_text.append(f"{time_str} {text}")

        return "\n".join(segments_text)

    def _calculate_topic_range(self, duration_minutes: float, granularity: str = "long") -> tuple[int, int]:
        """
        Вычисление динамического диапазона топиков на основе длительности пары.

        Режимы:
        - long (длинный режим, детальнее):
          - 50 минут -> 10–14
          - 90 минут -> 14–20
          - 120 минут -> 18–24
          - 180 минут -> 22–28
        - short (короткий режим, крупнее):
          - 50 минут -> 3–5
          - 90 минут -> 5–8
          - 120 минут -> 6–9
          - 180 минут -> 8–12

        Args:
            duration_minutes: Длительность пары в минутах
            granularity: "short" или "long"

        Returns:
            Кортеж (min_topics, max_topics)
        """
        duration_minutes = max(50, min(180, duration_minutes))

        if granularity == "short":
            # Короткий режим: меньше тем, крупнее (5-10 тем для 90-минутной лекции)
            min_topics = int(3 + (duration_minutes - 50) * 4 / 130)
            max_topics = int(5 + (duration_minutes - 50) * 5 / 130)
            min_topics = max(3, min(8, min_topics))
            max_topics = max(5, min(12, max_topics))
            return min_topics, max_topics

        min_topics = int(10 + (duration_minutes - 50) * 8 / 130)
        max_topics = int(16 + (duration_minutes - 50) * 10 / 130)
        min_topics = max(10, min(18, min_topics))
        max_topics = max(16, min(26, max_topics))

        return min_topics, max_topics

    async def _analyze_full_transcript(
        self,
        transcript: str,
        total_duration: float,
        recording_topic: str | None = None,
        min_topics: int = 10,
        max_topics: int = 30,
        granularity: str = "long",  # "short" | "long"
        segments: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Анализ полной транскрипции через DeepSeek.

        Args:
            transcript: Полная транскрипция с временными метками
            total_duration: Общая длительность видео в секундах
            recording_topic: Название курса/предмета

        Returns:
            Словарь с основными темами и детализированными топиками
        """
        context_line = ""
        if recording_topic:
            context_line = f"\nКонтекст: это лекция по курсу '{recording_topic}'.\n"

        if granularity == "short":
            min_spacing_minutes = max(10, min(18, total_duration / 60 * 0.12))
        else:  # granularity == "long"
            min_spacing_minutes = max(4, min(6, total_duration / 60 * 0.05))

        long_pauses = self._detect_long_pauses(segments or [], min_gap_minutes=8)
        pauses_instruction = ""
        if long_pauses:
            pauses_lines = [
                f"- {self._format_time(pause['start'])} – {self._format_time(pause['end'])} (≈{pause['duration_minutes']:.1f} мин)"
                for pause in long_pauses
            ]
            pauses_instruction = "\n\n⚠️ ВАЖНО: Найдены перерывы >=8 минут. ОБЯЗАТЕЛЬНО добавь их в список тем:\n" + "\n".join(pauses_lines) + "\n\nДля каждой паузы: [HH:MM:SS] - Перерыв (где HH:MM:SS — время начала из списка выше)."

        if granularity == "short":
            # Короткий режим: упрощенный промпт с крупными темами
            prompt = f"""Проанализируй транскрипцию учебной лекции и выдели структуру:{context_line}{pauses_instruction}

## ОСНОВНАЯ ТЕМА ПАРЫ

Выведи РОВНО ОДНУ тему (2–3 слова):{f" Название темы НЕ должно содержать слова из названия курса '{recording_topic}'. Если тема содержит такие слова — убери их. Например, если курс называется 'Прикладной Python', а тема 'Асинхронное программирование Python', напиши только 'Асинхронное программирование'." if recording_topic else ""}
Название темы

Примеры: "Stable Diffusion", "Архитектура трансформеров", "Generative Models"

## ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ ({min_topics}-{max_topics} топиков)

Формат: [HH:MM:SS] - Название топика

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Количество: {min_topics}-{max_topics} топиков (ориентируйся на естественные смены тем).
2. Длительность: ориентировочно 8–20 минут на тему, НО ГЛАВНОЕ — смена темы должна соответствовать РЕАЛЬНОМУ изменению содержания лекции.
3. ПРИОРИТЕТ: Определяй границы тем по СОДЕРЖАНИЮ транскрипции, а не по времени. Темы могут быть разной длины (6-25 минут), если это отражает структуру лекции.
4. Если явная смена темы происходит раньше 8 минут — это нормально, укажи её.
5. Если одна тема длится 20+ минут без явных подтем — оставь её цельной.
6. Минимальный шаг между темами: {min_spacing_minutes:.1f} минут (только если темы действительно разные).
7. Названия: 3–6 слов, информативные, на русском или английском (по терминологии).
8. Хронологический порядок.
9. Только фактические темы из транскрипции.

ФИНАЛЬНАЯ ПРОВЕРКА:
- Количество: {min_topics}-{max_topics} тем
- Длительность: в основном 8–20 минут (допустимы отклонения, если это естественная структура)
- Перерывы: все >=8 минут добавлены (если были указаны)
- Границы тем соответствуют РЕАЛЬНЫМ сменам содержания, а не просто временным интервалам

Если видишь, что разметка получилась механической (ровно по X минут) — переразметь по реальному содержанию.

Транскрипция:
{transcript}
"""
        else:
            prompt = f"""Проанализируй транскрипцию учебной лекции и выдели структуру:{context_line}{pauses_instruction}

## ОСНОВНАЯ ТЕМА ПАРЫ

Выведи РОВНО ОДНУ тему (2–3 слова):{f" Название темы НЕ должно содержать слова из названия курса '{recording_topic}'. Если тема содержит такие слова — убери их. Например, если курс называется 'Прикладной Python', а тема 'Асинхронное программирование Python', напиши только 'Асинхронное программирование'." if recording_topic else ""}
Название темы

Примеры: "Stable Diffusion", "Архитектура трансформеров", "Generative Models"

## ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ ({min_topics}-{max_topics} топиков)

Формат: [HH:MM:SS] - Название топика

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Количество: {min_topics}-{max_topics} топиков (ориентируйся на естественные смены тем).
2. Длительность: ориентировочно 3–12 минут на тему, НО ГЛАВНОЕ — смена темы должна соответствовать РЕАЛЬНОМУ изменению содержания лекции.
3. ПРИОРИТЕТ: Определяй границы тем по СОДЕРЖАНИЮ транскрипции, а не по времени. Темы могут быть разной длины (2-15 минут), если это отражает структуру лекции.
4. Если явная смена темы происходит через 2 минуты — это нормально, укажи её.
5. Если одна тема длится 15+ минут без явных подтем — можно разбить на логические части.
6. Минимальный шаг между темами: {min_spacing_minutes:.1f} минут (только если темы действительно разные).
7. Названия: 3–6 слов, информативные, на русском или английском (по терминологии).
8. Хронологический порядок.
9. Только фактические темы из транскрипции.

ФИНАЛЬНАЯ ПРОВЕРКА:
- Количество: {min_topics}-{max_topics} тем
- Длительность: в основном 3–12 минут (допустимы отклонения, если это естественная структура)
- Перерывы: все >=8 минут добавлены (если были указаны)
- Границы тем соответствуют РЕАЛЬНЫМ сменам содержания, а не просто временным интервалам

Если видишь, что разметка получилась механической (ровно по X минут) — переразметь по реальному содержанию.

Транскрипция:
{transcript}
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты — самый лучший аналитик учебных материалов на магистратуре Computer Science. Анализируй транскрипции и выделяй структуру лекций."
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=self.config.temperature if self.config.temperature and self.config.temperature > 0 else 0.05,
                top_p=1.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                seed=self.config.seed if getattr(self.config, 'seed', None) is not None else None,
                max_tokens=self.config.max_tokens,
            )

            content = response.choices[0].message.content.strip()
            if not content:
                return {'main_topics': [], 'topic_timestamps': []}

            logger.debug(f"📝 Промпт отправлен в DeepSeek (первые 1000 символов):\n{prompt[:1000]}...")
            logger.debug(f"📝 Полный ответ от DeepSeek:\n{content}")

            parsed = self._parse_structured_response(content, total_duration)
            parsed['long_pauses'] = long_pauses
            logger.debug(f"📊 Результат парсинга: main_topics={parsed.get('main_topics')}, topic_timestamps={len(parsed.get('topic_timestamps', []))}")

            return parsed

        except Exception as error:
            logger.exception(
                format_log(
                    "Не удалось проанализировать транскрипт",
                    ошибка=str(error),
                )
            )
            return {'main_topics': [], 'topic_timestamps': []}

    def _detect_long_pauses(self, segments: list[dict], min_gap_minutes: float = 8.0) -> list[dict]:
        """
        Поиск длинных пауз между сегментами.

        Args:
            segments: Список сегментов (ожидается отсортированный список)
            min_gap_minutes: Минимальная длительность паузы (в минутах) для фиксации

        Returns:
            Список словарей с паузами: [{"start": float, "end": float, "duration_minutes": float}, ...]
        """
        if not segments:
            return []

        min_gap_seconds = min_gap_minutes * 60
        pauses: list[dict] = []

        sorted_segments = sorted(segments, key=lambda s: s.get('start', 0))

        for idx in range(len(sorted_segments) - 1):
            current = sorted_segments[idx]
            nxt = sorted_segments[idx + 1]

            current_end = float(current.get('end', current.get('start', 0) or 0))
            next_start = float(nxt.get('start', 0) or 0)

            gap = next_start - current_end
            if gap >= min_gap_seconds:
                pauses.append(
                    {
                        'start': current_end,
                        'end': next_start,
                        'duration_minutes': gap / 60,
                    }
                )

        return pauses

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Форматирование секунд в HH:MM:SS"""
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _parse_structured_response(self, text: str, total_duration: float) -> dict[str, Any]:
        """
        Парсинг структурированного ответа от DeepSeek.

        Формат ответа:
        ## ОСНОВНЫЕ ТЕМЫ ПАРЫ
        - Тема 1
        - Тема 2

        ## ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ С ТАЙМКОДАМИ
        [HH:MM:SS] - [Название топика]
        [HH:MM:SS] - [Название топика]

        Args:
            text: Текст ответа от DeepSeek
            total_duration: Общая длительность видео в секундах

        Returns:
            Словарь с основными темами и детализированными топиками
        """
        main_topics = []
        topic_timestamps = []

        lines = text.split('\n')

        in_main_topics = False
        in_detailed_topics = False
        main_topics_section_found = False

        timestamp_pattern = r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*[-–—]?\s*(.+)'

        # Сначала ищем основную тему в начале ответа (до секции детализированных топиков)
        found_main_topic_before_section = False
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Если нашли секцию детализированных топиков, проверяем все строки до неё
            if 'ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ' in line_stripped.upper() or 'ТОПИКИ С ТАЙМКОДАМИ' in line_stripped.upper():
                # Ищем тему во всех строках до этой секции (но не слишком далеко - максимум 10 строк)
                for j in range(max(0, i - 10), i):
                    candidate = lines[j].strip()
                    if candidate and not candidate.startswith('##') and not candidate.startswith('#'):
                        if 'выведи' in candidate.lower() or 'тема' in candidate.lower() or 'пример' in candidate.lower():
                            continue
                        if re.match(timestamp_pattern, candidate):
                            continue
                        topic_candidate = re.sub(r'^[-*•\d.)]+\s*', '', candidate).strip()
                        topic_candidate = re.sub(r'^\[.*?\]\s*', '', topic_candidate).strip()
                        if topic_candidate:
                            words = topic_candidate.split()
                            # Основная тема должна быть короткой (2-4 слова)
                            if 2 <= len(words) <= 4:
                                main_topics.append(topic_candidate if len(words) <= 3 else ' '.join(words[:3]))
                                logger.debug(f"✅ Найдена основная тема (перед секцией детализированных топиков): {topic_candidate}")
                                found_main_topic_before_section = True
                                break
                break

        # Если не нашли тему перед секцией, проверяем первые строки ответа
        if not found_main_topic_before_section:
            for _, line in enumerate(lines[:10]):
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith('##') or line_stripped.startswith('#'):
                    continue
                if re.match(timestamp_pattern, line_stripped):
                    break
                if 'выведи' in line_stripped.lower() or 'тема' in line_stripped.lower() or 'пример' in line_stripped.lower():
                    continue
                topic_candidate = re.sub(r'^[-*•\d.)]+\s*', '', line_stripped).strip()
                topic_candidate = re.sub(r'^\[.*?\]\s*', '', topic_candidate).strip()
                if topic_candidate:
                    words = topic_candidate.split()
                    if 2 <= len(words) <= 4:
                        main_topics.append(topic_candidate if len(words) <= 3 else ' '.join(words[:3]))
                        logger.debug(f"✅ Найдена основная тема (в начале ответа): {topic_candidate}")
                        break

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            if (
                'ОСНОВНЫЕ ТЕМЫ' in line.upper()
                or 'ОСНОВНЫЕ ТЕМЫ ПАРЫ' in line.upper()
                or 'ОСНОВНАЯ ТЕМА' in line.upper()
            ):
                in_main_topics = True
                in_detailed_topics = False
                main_topics_section_found = True
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and not next_line.startswith('##') and not next_line.startswith('#'):
                        topic_candidate = re.sub(r'^[-*•\d.)]+\s*', '', next_line).strip()
                        topic_candidate = re.sub(r'^\[.*?\]\s*', '', topic_candidate).strip()
                        if topic_candidate and len(topic_candidate) > 3 and 'выведи' not in topic_candidate.lower():
                            words = topic_candidate.split()
                            if len(words) <= 4:
                                main_topics.append(topic_candidate if len(words) <= 3 else ' '.join(words[:3]))
                                logger.debug(f"✅ Найдена основная тема (сразу после заголовка): {topic_candidate}")
                continue
            elif 'ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ' in line.upper() or 'ТОПИКИ С ТАЙМКОДАМИ' in line.upper():
                in_main_topics = False
                in_detailed_topics = True
                continue
            elif line.startswith('##'):
                in_main_topics = False
                in_detailed_topics = False
                continue

            # Если строка начинается с временной метки [HH:MM:SS], это детализированный топик
            # (даже если мы не нашли заголовок секции)
            timestamp_match = re.match(timestamp_pattern, line)
            if timestamp_match:
                in_detailed_topics = True
                in_main_topics = False
                # Парсим топик сразу
                hours_str, minutes_str, seconds_str, topic = timestamp_match.groups()
                if seconds_str is None:
                    hours = 0
                    minutes = int(hours_str)
                    seconds = int(minutes_str)
                else:
                    hours = int(hours_str)
                    minutes = int(minutes_str)
                    seconds = int(seconds_str)
                total_seconds = hours * 3600 + minutes * 60 + seconds
                if 0 <= total_seconds <= total_duration:
                    topic_timestamps.append({
                        'topic': topic.strip(),
                        'start': float(total_seconds),
                    })
                continue

            if in_main_topics:
                if not line or line.startswith('##') or line.startswith('#'):
                    continue

                topic = re.sub(r'^[-*•\d.)]+\s*', '', line).strip()
                topic = re.sub(r'^\[.*?\]\s*', '', topic).strip()

                if topic.startswith('[') and 'выведи' in topic.lower():
                    continue

                if topic and len(topic) > 3:
                    words = topic.split()
                    if len(words) > 7:
                        topic = ' '.join(words[:15]) + '...'
                    elif len(topic) > 150:
                        topic = topic[:150].rsplit(' ', 1)[0] + '...'
                    main_topics.append(topic)
                    logger.debug(f"✅ Найдена основная тема: {topic}")

            elif in_detailed_topics:
                match = re.match(timestamp_pattern, line)
                if match:
                    hours_str, minutes_str, seconds_str, topic = match.groups()

                    if seconds_str is None:
                        hours = 0
                        minutes = int(hours_str)
                        seconds = int(minutes_str)
                    else:
                        hours = int(hours_str)
                        minutes = int(minutes_str)
                        seconds = int(seconds_str)

                    total_seconds = hours * 3600 + minutes * 60 + seconds

                    if 0 <= total_seconds <= total_duration:
                        topic_timestamps.append({
                            'topic': topic.strip(),
                            'start': float(total_seconds),
                        })
                    else:
                        logger.debug(
                            format_log(
                                "Метка пропущена: вне допустимого диапазона",
                                тема=topic.strip(),
                                позиция_минут=round(total_seconds / 60, 1),
                                допустимый_диапазон=f"0-{round(total_duration / 60, 1)}",
                            )
                        )

        # Если не нашли топики через секции, пробуем парсить все строки с временными метками
        if not topic_timestamps:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                match = re.match(timestamp_pattern, line)
                if match:
                    hours_str, minutes_str, seconds_str, topic = match.groups()
                    if seconds_str is None:
                        hours = 0
                        minutes = int(hours_str)
                        seconds = int(minutes_str)
                    else:
                        hours = int(hours_str)
                        minutes = int(minutes_str)
                        seconds = int(seconds_str)
                    total_seconds = hours * 3600 + minutes * 60 + seconds
                    if 0 <= total_seconds <= total_duration:
                        topic_timestamps.append({
                            'topic': topic.strip(),
                            'start': float(total_seconds),
                        })

        if not topic_timestamps and not main_topics:
            topic_timestamps = self._parse_simple_timestamps(text, total_duration)

        if main_topics_section_found and not main_topics:
            logger.debug("⚠️ Секция основных тем найдена, но темы не извлечены. Пробуем найти тему в начале ответа...")
            for i, line in enumerate(lines):
                if 'ОСНОВНЫЕ ТЕМЫ' in line.upper() or 'ОСНОВНЫЕ ТЕМЫ ПАРЫ' in line.upper():
                    for j in range(i + 1, min(i + 5, len(lines))):
                        candidate = lines[j].strip()
                        if candidate and not candidate.startswith('##') and not candidate.startswith('#'):
                            topic_candidate = re.sub(r'^[-*•\d.)]+\s*', '', candidate).strip()
                            topic_candidate = re.sub(r'^\[.*?\]\s*', '', topic_candidate).strip()
                            if (topic_candidate and len(topic_candidate) > 3 and
                                'выведи' not in topic_candidate.lower() and
                                'тема' not in topic_candidate.lower() and
                                'пример' not in topic_candidate.lower()):
                                words = topic_candidate.split()
                                if 2 <= len(words) <= 4:
                                    main_topics.append(topic_candidate if len(words) <= 3 else ' '.join(words[:3]))
                                    logger.debug(f"✅ Найдена основная тема (fallback): {topic_candidate}")
                                    break
                    break

        processed_main_topics = []
        for topic in main_topics[:1]:
            topic = ' '.join(topic.split())
            if topic and len(topic) > 3:
                words = topic.split()
                if len(words) > 7:
                    topic = ' '.join(words[:7]) + '...'
                processed_main_topics.append(topic)

        if not processed_main_topics and main_topics_section_found:
            logger.warning(f"⚠️ Секция основных тем найдена, но не удалось извлечь тему. Первые строки ответа:\n{chr(10).join(lines[:10])}")

        return {
            'main_topics': processed_main_topics,
            'topic_timestamps': topic_timestamps,
        }

    def _parse_simple_timestamps(self, text: str, total_duration: float) -> list[dict]:
        """
        Парсинг простого формата временных меток (fallback).

        Формат: [HH:MM:SS] - [Название] или [HH:MM:SS] [Название]

        Args:
            text: Текст ответа
            total_duration: Общая длительность видео

        Returns:
            Список временных меток
        """
        timestamps = []
        lines = text.split('\n')

        # Паттерн для [HH:MM:SS] - [Название] или [HH:MM:SS] [Название]
        pattern = r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*[-–—]?\s*(.+)'

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            match = re.match(pattern, line)
            if match:
                hours_str, minutes_str, seconds_str, topic = match.groups()

                if seconds_str is None:
                    hours = 0
                    minutes = int(hours_str)
                    seconds = int(minutes_str)
                else:
                    hours = int(hours_str)
                    minutes = int(minutes_str)
                    seconds = int(seconds_str)

                total_seconds = hours * 3600 + minutes * 60 + seconds

                if 0 <= total_seconds <= total_duration:
                    timestamps.append({
                        'topic': topic.strip(),
                        'start': float(total_seconds),
                    })

        return timestamps

    def _filter_and_merge_topics(
        self, timestamps: list[dict], total_duration: float, min_topics: int = 10, max_topics: int = 30
    ) -> list[dict]:
        """
        Фильтрация и объединение топиков для получения нужного диапазона.

        Объединяет близкие по времени топики и ограничивает общее количество.

        Args:
            timestamps: Список всех топиков с start
            total_duration: Общая длительность видео в секундах
            min_topics: Минимальное количество топиков
            max_topics: Максимальное количество топиков

        Returns:
            Отфильтрованный список топиков
        """
        if not timestamps:
            return []

        duration_minutes = total_duration / 60
        min_spacing = max(180, min(300, duration_minutes * 60 * 0.04))

        sorted_timestamps = sorted(timestamps, key=lambda x: x.get('start', 0))

        if len(sorted_timestamps) <= max_topics:
            merged = []

            for ts in sorted_timestamps:
                start = ts.get('start', 0)
                topic = ts.get('topic', '').strip()

                if not topic:
                    continue

                if merged and (start - merged[-1].get('start', 0)) < min_spacing:
                    prev_topic = merged[-1].get('topic', '')
                    if len(topic) > len(prev_topic):
                        merged[-1]['topic'] = topic
                    if start < merged[-1].get('start', 0):
                        merged[-1]['start'] = start
                else:
                    merged.append(ts)

            return merged

        target_count = max_topics
        step = len(sorted_timestamps) / target_count

        filtered = []
        for i in range(target_count):
            idx = int(i * step)
            if idx < len(sorted_timestamps):
                filtered.append(sorted_timestamps[idx])

        merged = []

        for ts in filtered:
            start = ts.get('start', 0)
            topic = ts.get('topic', '').strip()

            if not topic:
                continue

            if merged and (start - merged[-1].get('start', 0)) < min_spacing:
                prev_topic = merged[-1].get('topic', '')
                if len(topic) > len(prev_topic):
                    merged[-1]['topic'] = topic
                if start < merged[-1].get('start', 0):
                    merged[-1]['start'] = start
            else:
                merged.append(ts)

        if len(merged) < min_topics:
            additional_step = len(sorted_timestamps) / (min_topics - len(merged))
            added_indices = set()

            for i in range(min_topics - len(merged)):
                idx = int(i * additional_step)
                if idx < len(sorted_timestamps):
                    if idx not in added_indices:
                        ts = sorted_timestamps[idx]
                        start = ts.get('start', 0)
                        topic = ts.get('topic', '').strip()

                        if topic:
                            too_close = False
                            for existing in merged:
                                if abs(start - existing.get('start', 0)) < min_spacing:
                                    too_close = True
                                    break

                            if not too_close:
                                merged.append(ts)
                                added_indices.add(idx)

            # Сортируем по времени
            merged = sorted(merged, key=lambda x: x.get('start', 0))

        return merged

    def _add_end_timestamps(self, timestamps: list[dict], total_duration: float) -> list[dict]:
        """
        Добавление временных меток end для каждой темы.

        Args:
            timestamps: Список тем с start
            total_duration: Общая длительность видео

        Returns:
            Список тем с start и end
        """
        if not timestamps:
            return []

        sorted_timestamps = sorted(timestamps, key=lambda x: x.get('start', 0))

        result = []
        for i, ts in enumerate(sorted_timestamps):
            start = ts.get('start', 0)
            topic = ts.get('topic', '').strip()

            if not topic:
                continue

            if i < len(sorted_timestamps) - 1:
                end = sorted_timestamps[i + 1].get('start', 0)
            else:
                end = total_duration

            # Гарантируем минимальную длительность
            if end - start < 60 and i < len(sorted_timestamps) - 1:
                end = min(start + 60, sorted_timestamps[i + 1].get('start', 0))

            end = min(end, total_duration)

            if start >= end:
                logger.warning(
                    format_log(
                        "Тема пропущена из-за некорректных временных меток",
                        тема=topic,
                        начало_секунд=round(start, 1),
                        конец_секунд=round(end, 1),
                    )
                )
                continue

            result.append({
                'topic': topic,
                'start': start,
                'end': end,
            })

        return result


