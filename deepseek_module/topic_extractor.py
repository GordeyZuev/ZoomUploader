"""Извлечение тем из транскрипции через DeepSeek"""

import re
from typing import Any

from openai import AsyncOpenAI

from logger import get_logger

from .config import DeepSeekConfig

logger = get_logger()


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
            f"✅ TopicExtractor инициализирован: {config.base_url}, модель: {config.model}"
        )

    async def extract_topics(
        self, transcription_text: str, segments: list[dict] | None = None, recording_topic: str | None = None
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
            }
        """
        if not segments or len(segments) == 0:
            raise ValueError("Сегменты обязательны для извлечения тем")

        logger.info(f"🔍 Извлечение тем из {len(segments)} сегментов")
        if recording_topic:
            logger.info(f"📚 Контекст: {recording_topic}")

        total_duration = segments[-1].get('end', 0) if segments else 0
        duration_minutes = total_duration / 60
        logger.info(f"📊 Длительность видео: {duration_minutes:.1f} минут")

        # Вычисляем динамический диапазон топиков на основе длительности
        min_topics, max_topics = self._calculate_topic_range(duration_minutes)
        logger.info(f"📏 Диапазон топиков: {min_topics}-{max_topics} (для {duration_minutes:.1f} мин)")

        # Формируем полную транскрипцию с временными метками
        transcript_with_timestamps = self._format_transcript_with_timestamps(segments)

        # Отправляем всю транскрипцию в DeepSeek
        try:
            result = await self._analyze_full_transcript(
                transcript_with_timestamps, total_duration, recording_topic, min_topics, max_topics
            )

            main_topics = result.get('main_topics', [])
            topic_timestamps = result.get('topic_timestamps', [])

            # Фильтруем и объединяем топики для получения нужного диапазона
            filtered_timestamps = self._filter_and_merge_topics(topic_timestamps, total_duration, min_topics, max_topics)

            # Вычисляем end для каждой темы
            topic_timestamps_with_end = self._add_end_timestamps(filtered_timestamps, total_duration)

            logger.info(f"✅ Извлечено: {len(main_topics)} основных тем, {len(topic_timestamps_with_end)} детализированных топиков")

            return {
                'topic_timestamps': topic_timestamps_with_end,
                'main_topics': main_topics,
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при извлечении тем: {e}")
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
        # Шумовые паттерны, которые не несут учебного смысла (перерывы, субтитровые вставки и т.п.)
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

    def _calculate_topic_range(self, duration_minutes: float) -> tuple[int, int]:
        """
        Вычисление динамического диапазона топиков на основе длительности пары.

        Логика (увеличено на ~50%):
        - 50 минут (короткая пара) -> 18-24 топика
        - 90 минут (стандартная пара) -> 24-34 топика
        - 120 минут (длинная пара) -> 34-44 топика
        - 180 минут (очень длинная пара) -> 42-52 топика

        Args:
            duration_minutes: Длительность пары в минутах

        Returns:
            Кортеж (min_topics, max_topics)
        """
        # Ограничиваем диапазон: от 50 до 180 минут
        duration_minutes = max(50, min(180, duration_minutes))

        # Линейная интерполяция (увеличено количество)
        # Для 50 минут: min=18, max=24
        # Для 180 минут: min=42, max=52
        min_topics = int(18 + (duration_minutes - 50) * 24 / 130)
        max_topics = int(24 + (duration_minutes - 50) * 28 / 130)

        # Округляем до ближайших значений
        min_topics = max(18, min(42, min_topics))
        max_topics = max(24, min(52, max_topics))

        return min_topics, max_topics

    async def _analyze_full_transcript(
        self, transcript: str, total_duration: float, recording_topic: str | None = None,
        min_topics: int = 10, max_topics: int = 30
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

        # Вычисляем минимальное расстояние между топиками (примерно 3-5% от длительности)
        min_spacing_minutes = max(3, min(5, total_duration / 60 * 0.04))

        prompt = f"""Проанализируй предоставленную транскрипцию учебной пары/лекции и выдели следующую структуру:{context_line}

## ОСНОВНЫЕ ТЕМЫ ПАРЫ (РОВНО 1 тема, 2–3 слова)

[выведи РОВНО ОДНУ главную тему пары в очень краткой форме — 2–3 слова, подходящую для названия видео; одна строка без нумерации]

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
- Информативные и подробные названия (3-7 слов)
- Описывай конкретное содержание раздела
- Примеры хороших названий: "Практическое использование генераторов на примере чисел Фибоначчи", "Обработка исключений в генераторах через throw", "Сравнение асинхронности с многопоточностью и многопроцессностью"
- НЕ используй слишком короткие названия типа "Генераторы" или "Итераторы"

Требования:

- Только фактические темы из транскрипции (MUST). НИКОГДА не придумывай содержание (NEVER).
- Хронологический порядок (MUST).
- Названия информативны, 3–7 слов (MUST), без общих заголовков вроде «Введение», «Итоги» без контекста.
- Охватывай ключевые моменты лекции (MUST), без лишних мелких деталей.
- Количество топиков STRICT: минимум {min_topics}, максимум {max_topics} (MUST).
- Минимальный шаг между топиками: {min_spacing_minutes:.1f} минут (MUST).
- Длина топика целевая 5–8 минут; МАКСИМУМ 12–15 минут (MUST). Если дольше — разбивай на меньшие темы (MUST).
- Равномерное покрытие всей лекции (MUST). Финальная треть без «длинного хвоста» (MUST): последний пункт ≤10–15 минут.
- В последние 60 минут лекции выдели 8–12 подтем по 5–8 минут каждая (MUST).
- Перерывы/тишина/шум (MUST): внутри пауз темы НЕ выделяй (NEVER). Любая глава, чьи таймкоды пересекаются с паузой/тишиной/шумом, запрещена (NEVER). Если пауза ≤35 минут — выведи ровно одну строку «Перерыв N минут» с точными границами паузы; если пауза >35 минут — НЕ выводи отдельную тему перерыва, просто оставь этот интервал пустым и НЕ расширяй соседние темы на него (их end/start должны примыкать к границам паузы без перекрытия).
- Число N в тексте «Перерыв N минут» ОБЯЗАНО соответствовать длительности таймкода (MUST): N = округление((end − start) в минутах). Никогда не указывай «Перерыв 5 минут», если таймкод перекрывает >6 минут (NEVER).
- Если лектор явно объявляет «перерыв на X минут», зафиксируй таймкод перерыва длиной ровно X минут (start…start+X минут) и установи заголовок «Перерыв X минут» (MUST). Если фактическая тишина длится дольше X, остаток паузы не размечай отдельной темой и не расширяй соседние темы на него (NEVER). Если X > 35 — не выводи тему перерыва вовсе.
- Игнорируй субтитровые/технические вставки («Редактор субтитров», «Корректор», «Продолжение следует» и т.п.) (MUST).
- Темы должны начинаться только на реальных содержательных репликах лектора, а не в паузах/шуме (MUST).
- Разнообразие формулировок: избегай повторов, делай предметные заголовки (SHOULD).

В конце проверь себя (MUST) и при необходимости переразметь:
- Нет ни одной темы, пересекающейся по времени с перерывом/тишиной/шумовыми вставками.
- Для всех тем и перерыва(ов): длительность ≤15 минут; последний пункт ≤15 минут.
- Общее число тем в пределах [{min_topics}, {max_topics}].
- В последние 60 минут ≥8 подтем.
- Если остались «дыры» (непокрытые содержательные интервалы вне пауз), разбей соседние темы так, чтобы соблюсти шаг 5–8 мин и лимит 12–15 мин.

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
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

            content = response.choices[0].message.content.strip()
            if not content:
                return {'main_topics': [], 'topic_timestamps': []}

            # Парсим структурированный ответ
            return self._parse_structured_response(content, total_duration)

        except Exception as e:
            logger.error(f"❌ Ошибка при анализе транскрипции: {e}")
            return {'main_topics': [], 'topic_timestamps': []}

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

        # Паттерн для [HH:MM:SS] - [Название] или [HH:MM:SS] [Название]
        timestamp_pattern = r'\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*[-–—]?\s*(.+)'

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Определяем секции
            if 'ОСНОВНЫЕ ТЕМЫ' in line.upper() or 'ОСНОВНЫЕ ТЕМЫ ПАРЫ' in line.upper():
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
                            f"⚠️ Пропущена метка '{topic.strip()}' на {total_seconds/60:.1f} мин "
                            f"(вне диапазона: 0 - {total_duration/60:.1f} мин)"
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
                logger.warning(f"⚠️ Пропущена тема '{topic}' с некорректными метками: start={start:.1f}s >= end={end:.1f}s")
                continue

            result.append({
                'topic': topic,
                'start': start,
                'end': end,
            })

        return result


