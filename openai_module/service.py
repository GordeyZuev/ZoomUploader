"""Основной сервис для транскрибации и извлечения тем"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from deepseek_module import DeepSeekConfig, TopicExtractor
from logger import get_logger

from .audio_compressor import AudioCompressor
from .config import OpenAIConfig
from .transcription_service import TranscriptionService as WhisperService

logger = get_logger()


class TranscriptionService:
    """Основной сервис для транскрибации и обработки текста"""

    def __init__(self, openai_config: OpenAIConfig | None = None, deepseek_config: DeepSeekConfig | None = None):
        if openai_config is None:
            openai_config = OpenAIConfig.from_file()

        if not openai_config.validate():
            raise ValueError("Некорректная конфигурация OpenAI")

        if deepseek_config is None:
            deepseek_config = DeepSeekConfig.from_file()

        if not deepseek_config.validate():
            raise ValueError("Некорректная конфигурация DeepSeek")

        self.openai_config = openai_config
        self.deepseek_config = deepseek_config
        self.transcription_service = WhisperService(openai_config)
        self.topic_extractor = TopicExtractor(deepseek_config)
        self.audio_compressor = AudioCompressor(
            target_bitrate=openai_config.audio_bitrate,
            target_sample_rate=openai_config.audio_sample_rate,
            max_file_size_mb=openai_config.max_file_size_mb,
        )

        # Создаем директорию для транскрипций
        self.transcriptions_dir = Path("transcriptions")
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

    async def process_audio(
        self,
        audio_path: str,
        recording_id: int | None = None,
        recording_topic: str | None = None,
        granularity: str = "normal",  # "normal" | "coarse"
    ) -> dict[str, Any]:
        """
        Полная обработка аудио: сжатие, транскрибация, извлечение тем.

        Args:
            audio_path: Путь к аудио файлу
            recording_id: ID записи (для именования файлов)
            recording_topic: Название записи (для именования файлов)

        Returns:
            Словарь с результатами:
            {
                'transcription_file_path': str,
                'transcription_text': str,
                'topic_timestamps': list,
                'main_topics': list,
            }
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудио файл не найден: {audio_path}")

        logger.info(f"🎬 Начало обработки аудио: {audio_path}")

        # Шаг 1: Подготовка аудио (сжатие и разбиение, если нужно)
        prepared_audio, temp_files_to_cleanup = await self._prepare_audio(audio_path)

        # Определяем, это один файл или несколько частей
        is_multipart = isinstance(prepared_audio, list)
        audio_files = prepared_audio if is_multipart else [prepared_audio]

        try:
            # Шаг 2: Транскрибация (одного файла или нескольких частей)
            if is_multipart:
                logger.info(f"🎤 Параллельная транскрибация {len(audio_files)} частей через Whisper API...")
                start_time = time.time()

                # Сначала получаем длительность каждой части для расчета временных смещений (параллельно)
                logger.info("📊 Получение информации о длительности частей...")
                duration_tasks = [
                    self.audio_compressor.get_audio_info(part_path)
                    for part_path in audio_files
                ]
                audio_infos = await asyncio.gather(*duration_tasks)
                part_durations = [info['duration'] for info in audio_infos]

                # Вычисляем временные смещения для каждой части
                time_offsets = []
                cumulative_offset = 0.0
                for duration in part_durations:
                    time_offsets.append(cumulative_offset)
                    cumulative_offset += duration

                logger.info(
                    f"✅ Длительности частей получены: {[f'{d/60:.1f} мин' for d in part_durations]}\n"
                    f"   Временные смещения: {[f'{o/60:.1f} мин' for o in time_offsets]}"
                )

                # Запускаем все транскрибации параллельно
                parallel_start_time = time.time()
                logger.info("🚀 Запуск параллельной транскрибации всех частей...")

                # Создаем задачи для параллельной обработки
                async def transcribe_part_with_logging(part_index: int, part_path: str, part_duration: float) -> tuple[int, dict[str, Any], float]:
                    """Обертка для транскрибации с логированием и отслеживанием времени"""
                    part_num = part_index + 1
                    part_start_time = time.time()
                    time_since_parallel_start = part_start_time - parallel_start_time
                    logger.info(
                        f"\n{'='*60}\n"
                        f"   📤 ЗАПУСК ТРАНСКРИБАЦИИ ЧАСТИ {part_num}/{len(audio_files)}\n"
                        f"   📁 Файл: {os.path.basename(part_path)}\n"
                        f"   ⏱️  Время с начала параллельного запуска: {time_since_parallel_start:.2f} сек\n"
                        f"{'='*60}"
                    )
                    try:
                        # Передаем длительность для более точной оценки времени
                        result = await self.transcription_service.transcribe_audio(
                            part_path,
                            language="ru",
                            audio_duration=part_duration
                        )
                        part_elapsed_time = time.time() - part_start_time
                        logger.info(
                            f"\n{'='*60}\n"
                            f"   ✅ ЧАСТЬ {part_num}/{len(audio_files)} ЗАВЕРШЕНА\n"
                            f"   ⏱️  Общее время: {part_elapsed_time/60:.1f} мин ({part_elapsed_time:.1f} сек)\n"
                            f"   📝 Символов: {len(result.get('text', ''))}\n"
                            f"   📊 Сегментов: {len(result.get('segments', []))}\n"
                            f"{'='*60}\n"
                        )
                        return (part_num, result, part_elapsed_time)
                    except Exception as e:
                        part_elapsed_time = time.time() - part_start_time
                        logger.error(
                            f"\n{'='*60}\n"
                            f"   ❌ ОШИБКА ТРАНСКРИБАЦИИ ЧАСТИ {part_num}/{len(audio_files)}\n"
                            f"   ⏱️  Время до ошибки: {part_elapsed_time/60:.1f} мин\n"
                            f"   ❌ Ошибка: {e}\n"
                            f"{'='*60}\n"
                        )
                        raise

                transcription_tasks = [
                    transcribe_part_with_logging(i, part_path, part_durations[i])
                    for i, part_path in enumerate(audio_files)
                ]

                # Ждем завершения всех транскрибаций (return_exceptions=True для обработки ошибок)
                part_results = await asyncio.gather(*transcription_tasks, return_exceptions=True)

                # Проверяем результаты на ошибки и собираем информацию о времени
                errors = []
                successful_results = []
                part_times = {}  # part_num -> elapsed_time

                for result in part_results:
                    if isinstance(result, Exception):
                        errors.append(result)
                        logger.error(f"❌ Ошибка при транскрибации: {result}")
                    else:
                        part_num, part_result, part_time = result
                        successful_results.append((part_num, part_result))
                        part_times[part_num] = part_time

                if errors:
                    error_msg = f"Ошибки транскрибации в {len(errors)} частях из {len(part_results)}"
                    logger.error(f"❌ {error_msg}")
                    if not successful_results:
                        # Если все части упали, выбрасываем исключение
                        raise RuntimeError(error_msg) from errors[0]
                    else:
                        logger.warning(f"⚠️ Продолжаем с {len(successful_results)} успешными частями из {len(part_results)}")

                elapsed_time = time.time() - start_time

                # Расчет ускорения на основе реального времени обработки частей
                if part_times:
                    sequential_time = sum(part_times.values()) / 60  # Сумма времени всех частей (если бы последовательно)
                    parallel_time = elapsed_time / 60  # Фактическое время параллельной обработки
                    speedup = sequential_time / parallel_time if parallel_time > 0 else 1
                    max_part_time = max(part_times.values()) / 60  # Время самой долгой части

                    # Логируем детальную информацию о времени каждой части
                    time_details = ", ".join([
                        f"часть {num}: {time/60:.1f} мин"
                        for num, time in sorted(part_times.items())
                    ])

                    logger.info(
                        f"✅ Все транскрибации завершены за {parallel_time:.1f} минут\n"
                        f"   📊 Успешно: {len(successful_results)}/{len(part_results)} частей\n"
                        f"   ⏱️  Время частей: {time_details}\n"
                        f"   ⚡ Ускорение: ~{speedup:.1f}x "
                        f"(последовательно заняло бы ~{sequential_time:.1f} мин, "
                        f"теоретический минимум: ~{max_part_time:.1f} мин)"
                    )

                    # Проверяем, нет ли большой разницы во времени обработки частей
                    if len(part_times) > 1:
                        times_list = list(part_times.values())
                        max_time = max(times_list)
                        min_time = min(times_list)
                        time_diff_ratio = (max_time - min_time) / min_time if min_time > 0 else 0

                        if time_diff_ratio > 1.0:  # Разница больше 100%
                            logger.warning(
                                f"⚠️ Большая разница во времени обработки частей: "
                                f"самая быстрая {min_time/60:.1f} мин, самая медленная {max_time/60:.1f} мин "
                                f"(разница {time_diff_ratio*100:.0f}%). "
                                f"Возможные причины: разная нагрузка на серверах OpenAI, задержка сети, "
                                f"очередь на обработку."
                            )
                else:
                    logger.info(f"✅ Все транскрибации завершены за {elapsed_time/60:.1f} минут")

                # Объединяем результаты с учетом временных смещений
                all_transcriptions = []
                all_segments = []

                # Создаем словарь результатов по номеру части (part_num -> result)
                results_dict = {part_num: result for part_num, result in successful_results}

                for part_index, _part_path in enumerate(audio_files):
                    part_num = part_index + 1
                    if part_num in results_dict:
                        part_result = results_dict[part_num]
                        time_offset = time_offsets[part_index]

                        # Объединяем текст
                        all_transcriptions.append(part_result['text'])

                        # Объединяем сегменты с учетом временного смещения
                        part_segments = part_result.get('segments', [])
                        for seg in part_segments:
                            # Создаем копию сегмента, чтобы не изменять оригинал
                            adjusted_seg = seg.copy()
                            adjusted_seg['start'] = seg.get('start', 0) + time_offset
                            adjusted_seg['end'] = seg.get('end', 0) + time_offset
                            all_segments.append(adjusted_seg)

                        logger.debug(
                            f"   ✅ Часть {part_num}: {len(part_result['text'])} символов, "
                            f"{len(part_segments)} сегментов, смещение: {time_offset/60:.1f} мин"
                        )
                    else:
                        # Пропускаем части с ошибками
                        logger.warning(f"   ⚠️ Часть {part_num} пропущена из-за ошибки")

                # Сортируем сегменты по времени начала (на случай, если порядок нарушен)
                all_segments.sort(key=lambda x: x.get('start', 0))

                transcription_text = "\n\n".join(all_transcriptions)
                segments = all_segments

                # Берем язык из первой успешной части
                if successful_results:
                    transcription_language = successful_results[0][1].get('language', 'ru')
                else:
                    transcription_language = 'ru'

                total_time = time.time() - start_time
                logger.info(
                    f"✅ Транскрибация завершена: {len(transcription_text)} символов, "
                    f"{len(segments)} сегментов\n"
                    f"   ⏱️  Общее время: {total_time/60:.1f} минут"
                )
            else:
                logger.info("🎤 Транскрибация аудио через Whisper API...")
                transcription_result = await self.transcription_service.transcribe_audio(
                    prepared_audio, language="ru"
                )

                transcription_text = transcription_result['text']
                segments = transcription_result.get('segments', [])
                transcription_language = transcription_result.get('language', 'ru')

                logger.info(f"✅ Транскрибация завершена: {len(transcription_text)} символов, {len(segments)} сегментов")

            # Шаг 3: Извлечение тем
            logger.info("🔍 Извлечение тем через DeepSeek...")
            topics_result = await self.topic_extractor.extract_topics(
                transcription_text, segments, recording_topic=recording_topic, granularity=granularity
            )

            logger.info("✅ Извлечение тем завершено")

            # Шаг 4: Сохранение транскрипции в файл с временными метками
            transcription_file_path = self._save_transcription(
                transcription_text,
                segments,
                recording_id=recording_id,
                recording_topic=recording_topic,
            )

            # Формируем результат
            result = {
                'transcription_file_path': transcription_file_path,
                'transcription_text': transcription_text,
                'topic_timestamps': topics_result.get('topic_timestamps', []),
                'main_topics': topics_result.get('main_topics', []),
                'language': transcription_language,
            }

            logger.info("✅ Обработка аудио завершена успешно")
            logger.info(
                f"📊 Результаты: {len(topics_result.get('topic_timestamps', []))} тем, "
                f"{len(topics_result.get('main_topics', []))} основных тем"
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

    async def _prepare_audio(self, audio_path: str) -> tuple[str | list[str], list[str]]:
        """
        Подготовка аудио: сжатие и разбиение, если нужно.

        Returns:
            tuple: (путь к файлу или список путей к частям, список временных файлов для удаления)
        """
        file_size = os.path.getsize(audio_path)
        file_size_mb = file_size / (1024 * 1024)
        temp_files = []

        # Если файл уже достаточно мал, возвращаем исходный путь
        if file_size_mb < self.openai_config.max_file_size_mb * 0.8:  # Оставляем запас
            logger.info(f"✅ Аудио файл уже достаточно мал ({file_size_mb:.2f} МБ), сжатие не требуется")
            return audio_path, []

        # Сжимаем аудио
        logger.info(f"🔧 Сжатие аудио для Whisper API ({file_size_mb:.2f} МБ -> ~{self.openai_config.max_file_size_mb} МБ)...")
        compressed_path = await self.audio_compressor.compress_audio(audio_path)
        temp_files.append(compressed_path)

        # Проверяем размер после сжатия
        compressed_size = os.path.getsize(compressed_path)
        compressed_size_mb = compressed_size / (1024 * 1024)

        # Если после сжатия все еще слишком большой, разбиваем на части
        if compressed_size_mb > self.openai_config.max_file_size_mb:
            logger.info(f"🔪 Файл все еще большой ({compressed_size_mb:.2f} МБ), разбиение на части...")
            # Используем 24 МБ (96% от лимита) для максимальной эффективности
            parts = await self.audio_compressor.split_audio(
                compressed_path, max_size_mb=self.openai_config.max_file_size_mb * 0.96
            )
            # Возвращаем части и список файлов для удаления (части + сжатый файл)
            return parts, parts + [compressed_path]

        # Возвращаем сжатый файл и список для удаления
        return compressed_path, [compressed_path]

    def _save_transcription(
        self,
        transcription_text: str,
        segments: list[dict[str, Any]],
        recording_id: int | None = None,
        recording_topic: str | None = None
    ) -> str:
        """
        Сохранение транскрипции в файл с временными метками.

        Args:
            transcription_text: Полный текст транскрипции
            segments: Список сегментов с временными метками
            recording_id: ID записи (для именования файлов)
            recording_topic: Название записи (для именования файлов)

        Returns:
            Относительный путь к сохраненному файлу
        """
        # Формируем имя файла
        if recording_id is not None:
            filename = f"transcription_{recording_id}.txt"
        elif recording_topic:
            # Санитизируем имя файла
            safe_topic = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in recording_topic)
            safe_topic = safe_topic.strip()[:100]  # Ограничиваем длину
            filename = f"transcription_{safe_topic}.txt"
        else:
            filename = f"transcription_{int(time.time())}.txt"

        file_path = (self.transcriptions_dir / filename).resolve()

        # Сохраняем транскрипцию с временными метками
        with open(file_path, 'w', encoding='utf-8') as f:
            if segments and len(segments) > 0:
                # Если есть сегменты, сохраняем с временными метками
                logger.info(f"📝 Сохранение транскрипции с {len(segments)} сегментами и временными метками")

                for seg in segments:
                    start_time = seg.get('start', 0)
                    end_time = seg.get('end', 0)
                    text = seg.get('text', '').strip()

                    if text:
                        # Форматируем временные метки
                        start_formatted = self._format_timestamp(start_time)
                        end_formatted = self._format_timestamp(end_time)

                        # Записываем сегмент с метками: [HH:MM:SS - HH:MM:SS] текст
                        f.write(f"[{start_formatted} - {end_formatted}] {text}\n")
            else:
                # Если сегментов нет, сохраняем просто текст (fallback)
                logger.warning("⚠️ Сегменты с временными метками отсутствуют, сохраняем только текст")
                f.write(transcription_text)

        logger.info(f"💾 Транскрипция сохранена: {file_path} ({len(segments) if segments else 0} сегментов)")

        # Возвращаем относительный путь
        try:
            return str(file_path.relative_to(Path.cwd()))
        except ValueError:
            # Если не удается получить относительный путь (другая файловая система и т.п.),
            # возвращаем абсолютный путь
            logger.warning(
                "⚠️ Не удалось получить относительный путь для транскрипции, используем абсолютный"
            )
            return str(file_path)

