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
        granularity: str = "normal",
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

        # Режимы гранулярности: булев флаг и строковый маркер
        is_coarse = True if (granularity == "coarse") else False
        granularity_str = "coarse" if is_coarse else "normal"

        # Вычисляем динамический диапазон топиков на основе длительности и требуемой гранулярности
        min_topics, max_topics = self._calculate_topic_range(duration_minutes, granularity=granularity_str)
        logger.info(
            format_log(
                "Рассчитан диапазон количества тем",
                минимум_тем=min_topics,
                максимум_тем=max_topics,
                длительность_минут=round(duration_minutes, 1),
            )
        )

        # Формируем полную транскрипцию с временными метками
        transcript_with_timestamps = self._format_transcript_with_timestamps(segments)

        # Отправляем всю транскрипцию в DeepSeek
        try:
            result = await self._analyze_full_transcript(
                transcript_with_timestamps,
                total_duration,
                recording_topic,
                min_topics,
                max_topics,
                granularity=granularity_str,
                segments=segments,
            )

            main_topics = result.get('main_topics', [])
            topic_timestamps = result.get('topic_timestamps', [])

            # Фильтруем и объединяем топики для получения нужного диапазона
            filtered_timestamps = self._filter_and_merge_topics(topic_timestamps, total_duration, min_topics, max_topics)

            # Вычисляем end для каждой темы
            topic_timestamps_with_end = self._add_end_timestamps(filtered_timestamps, total_duration)

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
        # Шумовые паттерны, которые не несут учебного смысла (технические вставки и т.п.)
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

    def _calculate_topic_range(self, duration_minutes: float, granularity: str = "normal") -> tuple[int, int]:
        """
        Вычисление динамического диапазона топиков на основе длительности пары.

        Режимы:
        - normal (умеренная гранулярность):
          - 50 минут -> 10–14
          - 90 минут -> 14–20
          - 120 минут -> 18–24
          - 180 минут -> 22–28
        - coarse (крупные темы):
          - 50 минут -> 2–3
          - 90 минут -> 3–5
          - 120 минут -> 4–6
          - 180 минут -> 6–8

        Args:
            duration_minutes: Длительность пары в минутах

        Returns:
            Кортеж (min_topics, max_topics)
        """
        # Ограничиваем диапазон: от 50 до 180 минут
        duration_minutes = max(50, min(180, duration_minutes))

        if granularity == "coarse":
            # 50 -> 2–3; 180 -> 6–8
            min_topics = int(2 + (duration_minutes - 50) * 4 / 130)
            max_topics = int(3 + (duration_minutes - 50) * 5 / 130)
            min_topics = max(2, min(6, min_topics))
            max_topics = max(3, min(8, max_topics))
            return min_topics, max_topics

        # normal: линейная интерполяция с меньшим количеством топиков (обобщаем)
        min_topics = int(10 + (duration_minutes - 50) * 12 / 130)
        max_topics = int(14 + (duration_minutes - 50) * 14 / 130)

        # Округляем и ограничиваем
        min_topics = max(10, min(22, min_topics))
        max_topics = max(14, min(28, max_topics))

        return min_topics, max_topics

    async def _analyze_full_transcript(
        self,
        transcript: str,
        total_duration: float,
        recording_topic: str | None = None,
        min_topics: int = 10,
        max_topics: int = 30,
        granularity: str = "normal",
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

        # Вычисляем минимальное расстояние между топиками
        is_coarse = (granularity == "coarse")
        if is_coarse:
            # Крупные темы требуют большего шага
            min_spacing_minutes = max(12, min(20, total_duration / 60 * 0.15))
        else:
            # Обычная детализация
            min_spacing_minutes = max(4, min(6, total_duration / 60 * 0.05))

        # Разные требования для режимов гранулярности
        if is_coarse:
            target_len_line = "Целевая длительность топика 15–30 минут; МАКСИМУМ 35 минут (STRICT MUST). Если дольше — ОБЯЗАТЕЛЬНО разбей (STRICT MUST)."
            tail_line = "Равномерное покрытие всей лекции (MUST). Финальная треть без «длинного хвоста»: ни одна тема >35 минут (STRICT MUST)."
            last_window_line = "В последние 90 минут лекции выдели 3–5 крупных подтем по 15–30 минут (STRICT MUST)."
            tail_check_line = "Для всех тем: длительность ≤35 минут; последний пункт ≤30–35 минут."
            last_window_check_line = "В последние 90 минут ≥3 подтем."
            gap_rule_line = "Если остались «дыры» (непокрытые содержательные интервалы вне пауз), разбей соседние темы так, чтобы соблюсти шаг 15–30 мин и лимит 35 мин."
        else:
            target_len_line = "Целевая длительность топика 8–12 минут; МАКСИМУМ 12 минут (STRICT MUST). Если дольше — ОБЯЗАТЕЛЬНО разбей на несколько тем (STRICT MUST)."
            tail_line = "Равномерное покрытие всей лекции (MUST). Финальная треть без «длинного хвоста»: ни одна тема >12 минут (STRICT MUST)."
            last_window_line = "В последние 90 минут лекции выдели 7–12 подтем по 8–12 минут (STRICT MUST)."
            tail_check_line = "Для всех тем: длительность ≤12 минут; последний пункт ≤12 минут. Если найдена тема >12 минут — ОБЯЗАТЕЛЬНО переразметь её на несколько тем."
            last_window_check_line = "В последние 90 минут ≥7 подтем."
            gap_rule_line = "Если остались «дыры» (непокрытые содержательные интервалы вне пауз), разбей соседние темы так, чтобы соблюсти шаг 8–12 мин и лимит 12 мин."

        long_pauses = self._detect_long_pauses(segments or [], min_gap_minutes=8)
        pauses_info = ""
        if long_pauses:
            pauses_lines = [
                f"- {self._format_time(pause['start'])} – {self._format_time(pause['end'])} (≈{pause['duration_minutes']:.1f} мин)"
                for pause in long_pauses
            ]
            pauses_info = "\n\n⚠️ ВАЖНО: Найдены длинные паузы/перерывы (>=8 минут). ОБЯЗАТЕЛЬНО добавь их в список тем с точными временными метками:\n" + "\n".join(pauses_lines) + "\n\nДля каждой паузы добавь строку в формате:\n[HH:MM:SS] - Перерыв\n\nГде HH:MM:SS — это время начала паузы из списка выше.\n"

        prompt = f"""Проанализируй предоставленную транскрипцию учебной пары/лекции и выдели следующую структуру:{context_line}{pauses_info}

## ОСНОВНЫЕ ТЕМЫ ПАРЫ (РОВНО 1 тема, 2–3 слова)

[выведи РОВНО ОДНУ тему пары в очень краткой форме — 2–3 слова, максимально описывающую содержание пары; одна строка без нумерации]

ВАЖНО для основных тем:
    - Ровно 1 тема (MUST)
    - Длина строго 2–3 слова (MUST), без лишних деталей и описаний
    - Примеры: "Архитектура трансформеров", "Асинхронность Python", "Функции генераторы"
    - НЕ используй длинные фразы типа "Эволюция генераторов Python и их использование для..."

## ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ С ТАЙМКОДАМИ ({min_topics}-{max_topics} топиков)

[здесь создай список подтем/разделов в хронологическом порядке с временными метками]

Формат для топиков:

[HH:MM:SS] - [Название топика/раздела]

ВАЖНО для детализированных топиков:
    - Информативные и предметные названия (3–6 слов)
    - Описывай конкретное содержание раздела
    - Каждая тема должна быть информативной и предметной, понятной студенту
    - Примеры хороших названий: "Практическое использование генераторов чисел Фибоначчи", "Обработка исключений в генераторах через throw", "Сравнение асинхронности с многопоточностью"
    - НЕ используй слишком короткие названия типа "Генераторы" или "Итераторы"

ТРЕБОВАНИЯ:
    - Только фактические темы из транскрипции (MUST). НИКОГДА не придумывай содержание (NEVER).
    - Хронологический порядок (MUST).
    - Названия информативны, 3–6 слов (MUST).
    - Охватывай ключевые моменты лекции (MUST), избегая мелкой детализации.
    - Количество топиков STRICT: минимум {min_topics}, максимум {max_topics} (MUST).
    - Минимальный шаг между топиками: {min_spacing_minutes:.1f} минут (MUST).
    - {target_len_line}
    - {tail_line}
    - {last_window_line}
    - ПЕРЕРЫВЫ (MUST): Если в списке выше указаны паузы/перерывы >=8 минут, ОБЯЗАТЕЛЬНО добавь их в список тем в хронологическом порядке. Для каждой паузы используй формат: [HH:MM:SS] - Перерыв, где HH:MM:SS — это время начала паузы из списка выше. Перерывы считаются как отдельные элементы в общем количестве тем.
    - Игнорируй короткие паузы/тишину/технические вставки (MUST): внутри таких интервалов НЕ выделяй темы (NEVER), но длинные перерывы (>=8 минут) ОБЯЗАТЕЛЬНО добавляй.
    - Если тема излишне большая (больше 12 минут) — ОБЯЗАТЕЛЬНО разбей на меньшие темы (STRICT MUST). Никогда не оставляй темы длиннее 12 минут.
    - Темы должны начинаться только на реальных содержательных репликах лектора, а не в паузах/шуме (MUST).
    - Избегай повторов, делай предметные заголовки (SHOULD).

В конце проверь себя (MUST) и при необходимости переразметь:
    - Темы понятны и интуитивно ясны для студента.
    - Нет пересечений по времени с тишиной/шумовыми вставками.
    - ПЕРЕРЫВЫ ПРОВЕРКА: Если в начале промпта были указаны паузы/перерывы, убедись, что ВСЕ они добавлены в список тем с правильными временными метками (MUST).
    - {tail_check_line}

    - Общее число тем в пределах [{min_topics}, {max_topics}].
        - {last_window_check_line}
        - {gap_rule_line}
    - ФИНАЛЬНЫЙ ОТРЕЗОК: последний топик заканчивается на последней содержательной реплике. Не допускай «длинного хвоста» в конце — если остаётся длинный участок, разбей его на несколько тем так, чтобы каждая была ≤12 минут, с предметными названиями.
    - ПРОВЕРКА ДЛИТЕЛЬНОСТИ (MUST): Перед финальной отправкой проверь каждую тему. Если найдена тема длиннее 12 минут, ОБЯЗАТЕЛЬНО разбей её на 2–3 более мелкие темы с предметными названиями. Никогда не оставляй темы >12 минут.
    - Если нарушено ХОТЬ ОДНО правило (например, тема >12 минут или в последние 90 минут <7 подтем, или перерывы не добавлены), ПЕРЕРАЗМЕТЬ список тем до полного выполнения всех правил. Возвращай только корректный итог без нарушений.

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
                top_p=0.1,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                seed=self.config.seed if getattr(self.config, 'seed', None) is not None else None,
                max_tokens=self.config.max_tokens,
            )

            content = response.choices[0].message.content.strip()
            if not content:
                return {'main_topics': [], 'topic_timestamps': []}

            # Парсим структурированный ответ
            parsed = self._parse_structured_response(content, total_duration)
            parsed['long_pauses'] = long_pauses
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

        # Ищем секцию основных тем
        in_main_topics = False
        in_detailed_topics = False

        # Паттерны:
        # 1) [HH:MM:SS] - Название
        timestamp_pattern = r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*[-–—]?\s*(.+)'
        # 2) [HH:MM:SS - HH:MM:SS] (N мин) Название  — поддержка нового формата (обрабатывается на этапе форматирования вывода)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Определяем секции
            if (
                'ОСНОВНЫЕ ТЕМЫ' in line.upper()
                or 'ОСНОВНЫЕ ТЕМЫ ПАРЫ' in line.upper()
                or 'ОСНОВНАЯ ТЕМА' in line.upper()
            ):
                in_main_topics = True
                in_detailed_topics = False
                continue
            elif 'ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ' in line.upper() or 'ТОПИКИ С ТАЙМКОДАМИ' in line.upper():
                in_main_topics = False
                in_detailed_topics = True
                continue
            elif line.startswith('##'):
                # Новая секция
                in_main_topics = False
                in_detailed_topics = False
                continue

            # Парсим основные темы
            if in_main_topics:
                # Убираем маркеры списка (-, *, 1., и т.д.)
                topic = re.sub(r'^[-*•\d.]+\s*', '', line).strip()
                if topic and len(topic) > 3:
                    # Обрезаем слишком длинные темы (максимум 3-4 слова)
                    words = topic.split()
                    if len(words) > 4:
                        topic = ' '.join(words[:4])
                    main_topics.append(topic)

            # Парсим детализированные топики
            elif in_detailed_topics:
                match = re.match(timestamp_pattern, line)
                if match:
                    hours_str, minutes_str, seconds_str, topic = match.groups()

                    # Обрабатываем формат [M:SS] или [H:MM:SS]
                    if seconds_str is None:
                        hours = 0
                        minutes = int(hours_str)
                        seconds = int(minutes_str)
                    else:
                        hours = int(hours_str)
                        minutes = int(minutes_str)
                        seconds = int(seconds_str)

                    total_seconds = hours * 3600 + minutes * 60 + seconds

                    # Валидация времени
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

        # Если не нашли структурированный формат, пытаемся парсить как простой список
        if not topic_timestamps and not main_topics:
            topic_timestamps = self._parse_simple_timestamps(text, total_duration)

        # Постобработка основных тем: берём только первую и обрезаем до 2–3 слов
        processed_main_topics = []
        for topic in main_topics[:1]:  # Ровно одна тема
            # Обрезаем до 3 слов максимум
            words = topic.split()
            if len(words) > 3:
                topic = ' '.join(words[:3])
            # Убираем лишние пробелы
            topic = ' '.join(topic.split())
            if topic and len(topic) > 3:
                processed_main_topics.append(topic)

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

        # Вычисляем минимальное расстояние между топиками (примерно 3-5% от длительности)
        duration_minutes = total_duration / 60
        min_spacing = max(180, min(300, duration_minutes * 60 * 0.04))  # 3-5 минут в секундах

        # Сортируем по времени начала
        sorted_timestamps = sorted(timestamps, key=lambda x: x.get('start', 0))

        # Если топиков меньше максимума, возвращаем как есть (но проверяем минимальное расстояние)
        if len(sorted_timestamps) <= max_topics:
            # Объединяем слишком близкие топики
            merged = []

            for ts in sorted_timestamps:
                start = ts.get('start', 0)
                topic = ts.get('topic', '').strip()

                if not topic:
                    continue

                # Если есть предыдущий топик и расстояние меньше минимума
                if merged and (start - merged[-1].get('start', 0)) < min_spacing:
                    # Объединяем с предыдущим (берем более информативное название)
                    prev_topic = merged[-1].get('topic', '')
                    if len(topic) > len(prev_topic):
                        merged[-1]['topic'] = topic
                    # Обновляем время на более раннее
                    if start < merged[-1].get('start', 0):
                        merged[-1]['start'] = start
                else:
                    merged.append(ts)

            return merged

        # Если топиков больше максимума, нужно сократить
        # Используем стратегию: равномерно распределяем по времени
        target_count = max_topics
        step = len(sorted_timestamps) / target_count

        filtered = []
        for i in range(target_count):
            idx = int(i * step)
            if idx < len(sorted_timestamps):
                filtered.append(sorted_timestamps[idx])

        # Объединяем слишком близкие в результате
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

        # Если после объединения получилось меньше минимума, добавляем недостающие
        if len(merged) < min_topics:
            # Добавляем равномерно распределенные топики из исходного списка
            additional_step = len(sorted_timestamps) / (min_topics - len(merged))
            added_indices = set()

            for i in range(min_topics - len(merged)):
                idx = int(i * additional_step)
                if idx < len(sorted_timestamps):
                    # Проверяем, что не дублируем уже добавленные
                    if idx not in added_indices:
                        ts = sorted_timestamps[idx]
                        start = ts.get('start', 0)
                        topic = ts.get('topic', '').strip()

                        if topic:
                            # Проверяем, что не слишком близко к существующим
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

        # Сортируем по времени начала
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


