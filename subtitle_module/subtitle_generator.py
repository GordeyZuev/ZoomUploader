"""Subtitle generator from transcriptions (SRT and VTT formats)"""

import os
import re
from datetime import timedelta
from pathlib import Path

from logger import get_logger

logger = get_logger()


class SubtitleEntry:
    """Single subtitle entry"""

    def __init__(self, start_time: timedelta, end_time: timedelta, text: str):
        self.start_time = start_time
        self.end_time = end_time
        self.text = text.strip()

    def __repr__(self) -> str:
        return f"SubtitleEntry({self.start_time} -> {self.end_time}: {self.text[:50]}...)"


class SubtitleGenerator:
    """Generate subtitles from transcription files"""

    # Регулярное выражение для парсинга временных меток: [HH:MM:SS - HH:MM:SS]
    TIMESTAMP_PATTERN = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2})\]\s*(.*)")

    # Регулярное выражение для парсинга временных меток с миллисекундами: [HH:MM:SS.mmm - HH:MM:SS.mmm]
    TIMESTAMP_PATTERN_MS = re.compile(
        r"\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]\s*(.*)"
    )

    # Регулярное выражение для парсинга слов с миллисекундами (legacy)
    WORDS_TIMESTAMP_PATTERN = re.compile(
        r"\[(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})\]\s*(.*)"
    )

    def __init__(self, max_chars_per_line: int = 42, max_lines: int = 2):
        """
        Args:
            max_chars_per_line: Максимальное количество символов в строке субтитра
            max_lines: Максимальное количество строк в одном субтитре
        """
        self.max_chars_per_line = max_chars_per_line
        self.max_lines = max_lines

    def parse_transcription_file(self, file_path: str) -> list[SubtitleEntry]:
        """
        Парсит файл транскрипции и возвращает список записей субтитров.

        Args:
            file_path: Путь к файлу транскрипции

        Returns:
            Список объектов SubtitleEntry
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл транскрипции не найден: {file_path}")

        entries = []

        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                match_ms = self.TIMESTAMP_PATTERN_MS.match(line)
                match_s = self.TIMESTAMP_PATTERN.match(line) if not match_ms else None

                if match_ms or match_s:
                    try:
                        if match_ms:
                            start_h, start_m, start_s, start_ms = map(int, match_ms.groups()[:4])
                            end_h, end_m, end_s, end_ms = map(int, match_ms.groups()[4:8])
                            text = match_ms.groups()[8]
                            start_time = timedelta(
                                hours=start_h, minutes=start_m, seconds=start_s, milliseconds=start_ms
                            )
                            end_time = timedelta(hours=end_h, minutes=end_m, seconds=end_s, milliseconds=end_ms)
                        else:
                            start_h, start_m, start_s = map(int, match_s.groups()[:3])
                            end_h, end_m, end_s = map(int, match_s.groups()[3:6])
                            text = match_s.groups()[6]
                            start_time = timedelta(hours=start_h, minutes=start_m, seconds=start_s)
                            end_time = timedelta(hours=end_h, minutes=end_m, seconds=end_s)

                    except Exception as e:
                        logger.warning(f"⚠️ Ошибка парсинга строки {line_num} в файле {file_path}: {line[:50]}... - {e}")
                        continue

                    if text.strip():
                        entries.append(SubtitleEntry(start_time, end_time, text))
        return entries

    def parse_words_file(self, file_path: str) -> list[SubtitleEntry]:
        """
        Парсит файл транскрипции со словами и группирует их в субтитры.

        Args:
            file_path: Путь к файлу транскрипции со словами

        Returns:
            Список объектов SubtitleEntry (сгруппированные слова)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл транскрипции не найден: {file_path}")

        words = []
        total_lines = 0
        parsed_lines = 0

        logger.info(f"📖 Парсинг файла words: {file_path}")

        with open(file_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                total_lines += 1
                line = line.strip()
                if not line:
                    continue

                match = self.WORDS_TIMESTAMP_PATTERN.match(line)
                if match:
                    try:
                        # Извлекаем временные метки с миллисекундами
                        start_h, start_m, start_s, start_ms = map(int, match.groups()[:4])
                        end_h, end_m, end_s, end_ms = map(int, match.groups()[4:8])
                        word_text = match.groups()[8]

                        if word_text.strip():
                            # Создаем timedelta объекты с миллисекундами
                            start_time = timedelta(
                                hours=start_h, minutes=start_m, seconds=start_s, milliseconds=start_ms
                            )
                            end_time = timedelta(hours=end_h, minutes=end_m, seconds=end_s, milliseconds=end_ms)

                            words.append(
                                {
                                    "start": start_time,
                                    "end": end_time,
                                    "text": word_text.strip(),
                                }
                            )
                            parsed_lines += 1
                    except (ValueError, IndexError) as e:
                        logger.warning(f"⚠️ Ошибка парсинга строки {line_num} в файле {file_path}: {line[:50]}... - {e}")
                        continue
                else:
                    # Логируем только первые несколько нераспознанных строк, чтобы не засорять лог
                    if line_num <= 5:
                        logger.debug(
                            f"Строка не соответствует формату: line_num={line_num} | preview={line[:50]}... | file={file_path}"
                        )

        logger.info(f"📊 Парсинг завершен: обработано {total_lines} строк, распарсено {parsed_lines} слов")

        if not words:
            raise ValueError(f"Не удалось извлечь слова из файла {file_path}. Файл пуст или имеет неверный формат.")

        logger.info(f"🔄 Группировка {len(words)} слов в субтитры...")
        # Группируем слова в субтитры
        entries = self._group_words_into_subtitles(words)
        logger.info(f"✅ Создано {len(entries)} субтитров из {len(words)} слов")

        return entries

    def _group_words_into_subtitles(
        self, words: list[dict], max_duration_seconds: float = 5.0, pause_threshold_seconds: float = 0.5
    ) -> list[SubtitleEntry]:
        """
        Группирует слова в субтитры на основе времени и пауз.

        Args:
            words: Список словарей с ключами 'start', 'end', 'text' (timedelta)
            max_duration_seconds: Максимальная длительность субтитра в секундах
            pause_threshold_seconds: Порог паузы для начала нового субтитра (секунды)

        Returns:
            Список объектов SubtitleEntry
        """
        if not words:
            return []

        entries = []
        current_group = []
        current_start = None

        for word in words:
            word_start = word["start"]
            word_end = word["end"]

            # Определяем начало группы
            if current_start is None:
                current_start = word_start

            # Проверяем, нужно ли начать новую группу
            should_start_new = False

            # Проверка 1: Пауза между словами больше порога
            if current_group:
                last_word_end = current_group[-1]["end"]
                pause_duration = (word_start - last_word_end).total_seconds()
                if pause_duration > pause_threshold_seconds:
                    should_start_new = True

            # Проверка 2: Длительность текущей группы превышает максимум
            if not should_start_new:
                group_duration = (word_end - current_start).total_seconds()
                if group_duration > max_duration_seconds:
                    should_start_new = True

            # Если нужно начать новую группу, сохраняем текущую
            if should_start_new and current_group:
                # Формируем текст из слов текущей группы
                group_text = " ".join(w["text"] for w in current_group)
                group_start = current_start
                group_end = current_group[-1]["end"]

                entries.append(SubtitleEntry(group_start, group_end, group_text))

                # Начинаем новую группу
                current_group = [word]
                current_start = word_start
            else:
                # Добавляем слово в текущую группу
                current_group.append(word)

        # Добавляем последнюю группу
        if current_group:
            group_text = " ".join(w["text"] for w in current_group)
            group_start = current_start
            group_end = current_group[-1]["end"]
            entries.append(SubtitleEntry(group_start, group_end, group_text))

        return entries

    def _format_timedelta_srt(self, td: timedelta) -> str:
        """Форматирует timedelta в формат SRT: HH:MM:SS,mmm"""
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        milliseconds = int(td.microseconds / 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    def _format_timedelta_vtt(self, td: timedelta) -> str:
        """Форматирует timedelta в формат VTT: HH:MM:SS.mmm"""
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        milliseconds = int(td.microseconds / 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def _split_text(self, text: str) -> list[str]:
        """
        Разбивает текст на строки с учетом максимальной длины.

        Args:
            text: Текст для разбиения

        Returns:
            Список строк
        """
        words = text.split()
        lines = []
        current_line = []
        current_length = 0

        for word in words:
            word_length = len(word)

            # Если добавление слова превысит лимит, начинаем новую строку
            if current_length + word_length + (1 if current_line else 0) > self.max_chars_per_line:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = []
                    current_length = 0

                # Если достигли максимального количества строк, останавливаемся
                if len(lines) >= self.max_lines:
                    break

            current_line.append(word)
            current_length += word_length + (1 if len(current_line) > 1 else 0)

        # Добавляем оставшиеся слова
        if current_line and len(lines) < self.max_lines:
            lines.append(" ".join(current_line))

        return lines if lines else [text[: self.max_chars_per_line]]

    def generate_srt(self, entries: list[SubtitleEntry], output_path: str) -> str:
        """
        Генерирует файл субтитров в формате SRT.

        Args:
            entries: Список записей субтитров
            output_path: Путь для сохранения файла

        Returns:
            Путь к созданному файлу
        """
        with open(output_path, "w", encoding="utf-8") as f:
            for index, entry in enumerate(entries, start=1):
                # Номер субтитра
                f.write(f"{index}\n")

                # Временные метки
                start_str = self._format_timedelta_srt(entry.start_time)
                end_str = self._format_timedelta_srt(entry.end_time)
                f.write(f"{start_str} --> {end_str}\n")

                # Текст (разбитый на строки)
                lines = self._split_text(entry.text)
                for line in lines:
                    f.write(f"{line}\n")

                # Пустая строка между субтитрами
                f.write("\n")

        return output_path

    def generate_vtt(self, entries: list[SubtitleEntry], output_path: str) -> str:
        """
        Генерирует файл субтитров в формате VTT.

        Args:
            entries: Список записей субтитров
            output_path: Путь для сохранения файла

        Returns:
            Путь к созданному файлу
        """
        with open(output_path, "w", encoding="utf-8") as f:
            # Заголовок VTT
            f.write("WEBVTT\n\n")

            for entry in entries:
                # Временные метки
                start_str = self._format_timedelta_vtt(entry.start_time)
                end_str = self._format_timedelta_vtt(entry.end_time)
                f.write(f"{start_str} --> {end_str}\n")

                # Текст (разбитый на строки)
                lines = self._split_text(entry.text)
                for line in lines:
                    f.write(f"{line}\n")

                # Пустая строка между субтитрами
                f.write("\n")

        return output_path

    def generate_from_transcription(
        self, transcription_path: str, output_dir: str | None = None, formats: list[str] = None
    ) -> dict[str, str]:
        """
        Генерирует субтитры из файла транскрипции.
        Ожидается готовый segments.txt (с мс); других вариантов не используем.

        Args:
            transcription_path: Путь к файлу транскрипции
            output_dir: Директория для сохранения (по умолчанию - та же, что и транскрипция)
            formats: Список форматов для генерации ['srt', 'vtt'] (по умолчанию оба)

        Returns:
            Словарь с путями к созданным файлам: {'srt': path, 'vtt': path}
        """
        if formats is None:
            formats = ["srt", "vtt"]

        if output_dir is None:
            output_dir = os.path.dirname(transcription_path)

        os.makedirs(output_dir, exist_ok=True)

        entries = []
        base_name = "subtitles"

        if os.path.isdir(transcription_path):
            segments_path = os.path.join(transcription_path, "segments.txt")
            if os.path.exists(segments_path):
                logger.info(f"📝 Используем segments.txt: {segments_path}")
                entries = self.parse_transcription_file(segments_path)
            else:
                raise FileNotFoundError(f"В папке нет segments.txt: {transcription_path}")
        else:
            if Path(transcription_path).name == "segments.txt":
                logger.info(f"📝 Используем segments.txt: {transcription_path}")
                entries = self.parse_transcription_file(transcription_path)
            else:
                raise FileNotFoundError(
                    f"Ожидается segments.txt или папка с segments.txt, получено: {transcription_path}"
                )

        if not entries:
            raise ValueError(f"Не удалось извлечь записи из файла транскрипции: {transcription_path}")

        result = {}

        if "srt" in formats:
            srt_path = os.path.join(output_dir, f"{base_name}.srt")
            self.generate_srt(entries, srt_path)
            result["srt"] = srt_path

        if "vtt" in formats:
            vtt_path = os.path.join(output_dir, f"{base_name}.vtt")
            self.generate_vtt(entries, vtt_path)
            result["vtt"] = vtt_path

        return result
