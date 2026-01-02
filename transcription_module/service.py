"""Основной сервис для транскрибации и извлечения тем"""

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from deepseek_module import DeepSeekConfig, TopicExtractor
from fireworks_module import FireworksConfig, FireworksTranscriptionService
from logger import get_logger
from utils.audio_compressor import AudioCompressor
from utils.formatting import normalize_datetime_string

logger = get_logger()


class TranscriptionService:
    """Основной сервис для транскрибации и обработки текста"""

    def __init__(
        self,
        deepseek_config: DeepSeekConfig | None = None,
        fireworks_config: FireworksConfig | None = None,
    ):
        if deepseek_config is None:
            deepseek_config = DeepSeekConfig.from_file()

        self.deepseek_config = deepseek_config

        if fireworks_config is None:
            fireworks_config = FireworksConfig.from_file()

        self.fireworks_config = fireworks_config

        self.fireworks_service = FireworksTranscriptionService(self.fireworks_config)
        self.topic_extractor = TopicExtractor(self.deepseek_config)

        target_bitrate = self.fireworks_config.audio_bitrate
        target_sample_rate = self.fireworks_config.audio_sample_rate
        max_file_size_mb = self.fireworks_config.max_file_size_mb

        self.audio_compressor = AudioCompressor(
            target_bitrate=target_bitrate,
            target_sample_rate=target_sample_rate,
            max_file_size_mb=max_file_size_mb,
        )

        self.transcriptions_dir = Path("media/transcriptions")
        self.transcriptions_dir.mkdir(exist_ok=True)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """
        Форматирование времени в секундах в формат HH:MM:SS

        Args:
            seconds: Время в секундах (может быть float)

        Returns:
            Строка в формате HH:MM:SS
        """
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_timestamp_with_ms(seconds: float) -> str:
        """
        Форматирование времени в секундах в формат HH:MM:SS.mmm

        Args:
            seconds: Время в секундах (может быть float)

        Returns:
            Строка в формате HH:MM:SS.mmm
        """
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        milliseconds = int((seconds - total_seconds) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

    def _compose_fireworks_prompt(self, recording_topic: str | None) -> str:
        """Формирование подсказки для Fireworks с учетом предмета."""
        base_prompt = (self.fireworks_config.prompt or "").strip()
        topic = (recording_topic or "").strip()

        if base_prompt and topic:
            # Объединяем базовый промпт с названием пары в связный текст
            return f'{base_prompt} Название пары: "{topic}". Учитывай специфику этого курса при распознавании терминов.'
        elif base_prompt:
            # Только базовый промпт
            return base_prompt
        elif topic:
            # Только название пары с базовыми инструкциями
            return f'Это лекция магистратуры по Computer Science со специализацией в Machine Learning и Data Science. Название пары: "{topic}". Сохраняй правильное написание профильных терминов (включая английские), латинских обозначений, аббревиатур, элементов кода и имён собственных.'
        else:
            # Fallback - общие инструкции
            return "Это лекция магистратуры по Computer Science со специализацией в Machine Learning и Data Science. Сохраняй правильное написание профильных терминов (включая английские), латинских обозначений, аббревиатур, элементов кода и имён собственных."

    async def process_audio(
        self,
        audio_path: str,
        recording_id: int | None = None,
        recording_topic: str | None = None,
        recording_start_time: str | None = None,
        granularity: str = "long",  # "short" | "long"
    ) -> dict[str, Any]:
        """
        Полная обработка аудио: сжатие, транскрибация, извлечение тем.

        Args:
            audio_path: Путь к аудио файлу
            recording_id: ID записи (для именования файлов)
            recording_topic: Название записи (для именования файлов)
            granularity: Режим извлечения тем: "short" или "long"

        Returns:
            Словарь с результатами:
            {
                'transcription_dir': str,  # Путь к папке с файлами транскрипции
                'transcription_text': str,
                'topic_timestamps': list,
                'main_topics': list,
            }
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудио файл не найден: {audio_path}")

        logger.info(f"🎬 Начало обработки аудио: {audio_path} (модель: Fireworks)")

        fireworks_prompt = self._compose_fireworks_prompt(recording_topic)

        prepared_audio, temp_files_to_cleanup = await self._prepare_audio(audio_path)
        transcription_language = self.fireworks_config.language

        try:
            logger.info("🎆 Транскрибация аудио через Fireworks API...")
            transcription_result = await self.fireworks_service.transcribe_audio(
                audio_path=prepared_audio,
                language=transcription_language,
                prompt=fireworks_prompt,
            )

            transcription_text = transcription_result["text"]
            segments = transcription_result.get("segments", [])
            segments_auto = transcription_result.get("segments_auto", [])
            words = transcription_result.get("words", [])
            srt_content = transcription_result.get("srt_content")  # Оригинальный SRT от Fireworks
            transcription_language = transcription_result.get("language", "ru")

            logger.info(
                f"✅ Транскрибация завершена: {len(transcription_text)} символов, "
                f"{len(segments)} сегментов, {len(words)} слов"
            )

            transcription_dir = self._save_transcription(
                transcription_text,
                segments,
                words=words,
                segments_auto=segments_auto,
                srt_content=srt_content,
                recording_id=recording_id,
                recording_topic=recording_topic,
                recording_start_time=recording_start_time,
            )

            logger.info("🔍 Извлечение тем через DeepSeek из файла...")
            segments_file_path = Path(transcription_dir) / "segments.txt"
            topics_result = await self.topic_extractor.extract_topics_from_file(
                segments_file_path=str(segments_file_path),
                recording_topic=recording_topic,
                granularity=granularity,
            )

            logger.info("✅ Извлечение тем завершено")

            # Преобразуем паузы в формат временных меток
            topic_timestamps = topics_result.get("topic_timestamps", [])
            long_pauses = topics_result.get("long_pauses", [])

            # Проверяем, какие перерывы уже есть в topic_timestamps (добавленные моделью)
            existing_pause_starts = set()
            for ts in topic_timestamps:
                topic = ts.get("topic", "").strip()
                # Проверяем, является ли это перерывом (с учетом разных вариантов написания)
                if topic.lower() in ["перерыв", "pause", "break"]:
                    existing_pause_starts.add(ts.get("start", 0))

            # Добавляем паузы как отдельные временные метки, исключая дубликаты
            pause_timestamps = []
            for pause in long_pauses:
                pause_start = pause["start"]
                # Пропускаем паузы, которые уже добавлены моделью
                # Используем небольшой допуск (5 секунд) для учета возможных расхождений во времени
                if not any(abs(pause_start - existing_start) < 5.0 for existing_start in existing_pause_starts):
                    pause_timestamps.append(
                        {
                            "topic": "Перерыв",
                            "start": pause_start,
                            "end": pause["end"],
                            "type": "pause",
                            "duration_minutes": pause.get("duration_minutes", (pause["end"] - pause_start) / 60),
                        }
                    )

            # Объединяем темы и паузы, сортируем по времени начала
            all_timestamps = topic_timestamps + pause_timestamps
            all_timestamps.sort(key=lambda x: x.get("start", 0))

            # Формируем результат
            result = {
                "transcription_dir": transcription_dir,
                "transcription_text": transcription_text,
                "topic_timestamps": all_timestamps,
                "main_topics": topics_result.get("main_topics", []),
                "long_pauses": long_pauses,  # Сохраняем также исходные данные о паузах
                "language": transcription_language,
                "fireworks_raw": transcription_result,
            }

            logger.info("✅ Обработка аудио завершена успешно")
            topics_count = len(topic_timestamps)
            pauses_count = len(long_pauses)
            logger.info(
                f"📊 Результаты: {topics_count} тем, "
                f"{len(topics_result.get('main_topics', []))} основных тем, "
                f"{pauses_count} пауз"
            )

            return result

        finally:
            # Удаляем временные файлы, если они были созданы
            for temp_file in temp_files_to_cleanup:
                if temp_file != audio_path and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        logger.debug(f"🗑️ Удален временный файл: {temp_file}")
                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось удалить временный файл {temp_file}: {e}")

    async def _prepare_audio(self, audio_path: str) -> tuple[str, list[str]]:
        """
        Подготовка аудио: извлечение из видео, если нужно.
        Fireworks поддерживает большие файлы, поэтому разбиение не требуется.

        Args:
            audio_path: Путь к аудио файлу

        Returns:
            Tuple: (путь к файлу, список временных файлов для удаления)
        """
        file_size = os.path.getsize(audio_path)
        file_size_mb = file_size / (1024 * 1024)
        temp_files = []

        logger.info(f"🎆 Fireworks поддерживает большие файлы, разбиение не требуется ({file_size_mb:.2f} МБ)")

        # Проверяем, является ли файл видео (нужно извлечь аудио)
        is_video = audio_path.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v"))
        if is_video:
            logger.info("🎬 Обнаружен видео файл, извлечение аудио для Fireworks...")
            # Извлекаем аудио из видео (но не разбиваем)
            compressed_path = await self.audio_compressor.compress_audio(audio_path)
            temp_files.append(compressed_path)
            return compressed_path, temp_files

        # Если это уже аудио файл, возвращаем как есть
        return audio_path, []

    def _save_transcription(
        self,
        transcription_text: str,
        segments: list[dict[str, Any]],
        words: list[dict[str, Any]] | None = None,
        segments_auto: list[dict[str, Any]] | None = None,
        srt_content: str | None = None,
        recording_id: int | None = None,
        recording_topic: str | None = None,
        recording_start_time: str | None = None,
    ) -> str:
        """
        Сохранение транскрипции в папку с файлами.

        Структура папки:
        - transcription_<topic>/
          - words.txt (слова с временными метками)
          - segments.txt (сегменты с временными метками)
          - subtitles.srt (субтитры SRT)
          - subtitles.vtt (субтитры VTT)

        Args:
            transcription_text: Полный текст транскрипции
            segments: Список сегментов с временными метками
            words: Список слов с временными метками (обязательно для генерации субтитров)
            srt_content: Оригинальный SRT от Fireworks (опционально)
            recording_id: ID записи (для именования папки, если нет topic)
            recording_topic: Название записи (для именования папки, приоритетно)

        Returns:
            Относительный путь к папке с транскрипцией
        """
        if recording_topic:
            safe_topic = re.sub(r'[<>:"/\\|?*]', "_", recording_topic)
            safe_topic = re.sub(r"\s+", "_", safe_topic)
            safe_topic = safe_topic.strip("_")
            if len(safe_topic) > 200:
                safe_topic = safe_topic[:200]

            date_suffix = ""
            if recording_start_time:
                try:
                    normalized_time = normalize_datetime_string(recording_start_time)
                    date_obj = datetime.fromisoformat(normalized_time)
                    date_suffix = f"_{date_obj.strftime('%y-%m-%d_%H-%M')}"
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка парсинга даты '{recording_start_time}' для имени папки транскрипции: {e}")

            folder_name = f"transcription_{safe_topic}{date_suffix}"
        elif recording_id is not None:
            folder_name = f"transcription_{recording_id}"
        else:
            folder_name = f"transcription_{int(time.time())}"

        transcription_folder = (self.transcriptions_dir / folder_name).resolve()
        transcription_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"📁 Создана папка для транскрипции: {transcription_folder}")

        if words and len(words) > 0:
            words_file_path = transcription_folder / "words.txt"
            with open(words_file_path, "w", encoding="utf-8") as f:
                logger.info(f"📝 Сохранение транскрипции с {len(words)} словами и временными метками")

                for word_item in words:
                    start_time = word_item.get("start", 0) or 0.0
                    end_time = word_item.get("end", 0) or 0.0
                    word_text = word_item.get("word", "").strip()

                    if word_text:
                        start_formatted = self._format_timestamp_with_ms(start_time)
                        end_formatted = self._format_timestamp_with_ms(end_time)
                        f.write(f"[{start_formatted} - {end_formatted}] {word_text}\n")

            logger.info(f"💾 Транскрипция (слова) сохранена: {words_file_path} ({len(words)} слов)")
        else:
            logger.warning("⚠️ Слова не предоставлены, генерация субтитров может быть невозможна")

        def _write_segments_file(target_path: Path, segments_data: list[dict[str, Any]], label: str) -> None:
            with open(target_path, "w", encoding="utf-8") as f:
                if segments_data and len(segments_data) > 0:
                    logger.info(f"📝 Сохранение транскрипции с {len(segments_data)} сегментами ({label})")

                    for seg in segments_data:
                        start_time = seg.get("start", 0) or 0.0
                        end_time = seg.get("end", 0) or 0.0
                        text = seg.get("text", "").strip()

                        if text:
                            start_formatted = self._format_timestamp_with_ms(start_time)
                            end_formatted = self._format_timestamp_with_ms(end_time)
                            # Защита от одинаковых меток
                            if start_formatted == end_formatted:
                                end_time = float(end_time) + 0.001
                                end_formatted = self._format_timestamp_with_ms(end_time)
                            f.write(f"[{start_formatted} - {end_formatted}] {text}\n")
                else:
                    logger.warning(f"⚠️ Сегменты ({label}) отсутствуют, сохраняем только текст")
                    f.write(transcription_text)

        # segments.txt — сегменты, пришедшие из Fireworks API (приоритет)
        segments_file_path = transcription_folder / "segments.txt"
        _write_segments_file(segments_file_path, segments, "Fireworks API")
        logger.info(
            f"💾 Транскрипция (segments.txt, API) сохранена: {segments_file_path} "
            f"({len(segments) if segments else 0} сегментов)"
        )

        # segments_auto.txt — локально собранные сегменты из слов (для анализа/резерва)
        if segments_auto is not None:
            segments_auto_path = transcription_folder / "segments_auto.txt"
            _write_segments_file(segments_auto_path, segments_auto, "локальные (auto)")
            logger.info(
                f"💾 Транскрипция (segments_auto.txt, локальные) сохранена: {segments_auto_path} "
                f"({len(segments_auto) if segments_auto else 0} сегментов)"
            )

        if words and len(words) > 0:
            try:
                from subtitle_module import SubtitleGenerator

                generator = SubtitleGenerator()

                # Генерируем субтитры из segments.txt (уже сгруппированные сегменты)
                subtitle_source_path = str(segments_file_path)

                srt_target = transcription_folder / "subtitles.srt"
                vtt_target = transcription_folder / "subtitles.vtt"
                if srt_target.exists():
                    srt_target.unlink()
                if vtt_target.exists():
                    vtt_target.unlink()

                subtitle_result = generator.generate_from_transcription(
                    transcription_path=subtitle_source_path,
                    output_dir=str(transcription_folder),
                    formats=["srt", "vtt"],
                )

                if "srt" in subtitle_result:
                    srt_source = Path(subtitle_result["srt"])
                    if srt_source.exists() and srt_source != srt_target:
                        if srt_source.name != "subtitles.srt":
                            srt_source.rename(srt_target)
                        logger.info(f"✅ Создан SRT файл: {srt_target}")
                    elif srt_source == srt_target:
                        logger.info(f"✅ Создан SRT файл: {srt_target}")

                if "vtt" in subtitle_result:
                    vtt_source = Path(subtitle_result["vtt"])
                    if vtt_source.exists() and vtt_source != vtt_target:
                        if vtt_source.name != "subtitles.vtt":
                            vtt_source.rename(vtt_target)
                        logger.info(f"✅ Создан VTT файл: {vtt_target}")
                    elif vtt_source == vtt_target:
                        logger.info(f"✅ Создан VTT файл: {vtt_target}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось автоматически создать субтитры: {e}")

        if srt_content:
            srt_backup_path = transcription_folder / "subtitles_fireworks_original.srt"
            with open(srt_backup_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            logger.info(f"💾 Оригинальный SRT файл от Fireworks сохранен (резервный): {srt_backup_path}")

        try:
            return str(transcription_folder.relative_to(Path.cwd()))
        except ValueError:
            logger.warning("⚠️ Не удалось получить относительный путь для транскрипции, используем абсолютный")
            return str(transcription_folder)
