"""Основной сервис для транскрибации и извлечения тем"""

import asyncio
import math
import os
import time
from pathlib import Path
from typing import Any, Literal

from deepseek_module import DeepSeekConfig, TopicExtractor
from fireworks_module import FireworksConfig, FireworksTranscriptionService
from logger import get_logger

from .audio_compressor import AudioCompressor
from .config import OpenAIConfig
from .transcription_service import TranscriptionService as WhisperService

logger = get_logger()


TranscriptionProvider = Literal["fireworks", "whisper"]


class TranscriptionService:
    """Основной сервис для транскрибации и обработки текста"""

    def __init__(
        self,
        openai_config: OpenAIConfig | None = None,
        deepseek_config: DeepSeekConfig | None = None,
        fireworks_config: FireworksConfig | None = None,
    ):
        self.openai_config = openai_config
        if self.openai_config is None:
            try:
                self.openai_config = OpenAIConfig.from_file()
            except Exception as exc:
                logger.warning(
                    f"⚠️ Не удалось загрузить конфигурацию OpenAI: {exc}. Whisper-бэкенд будет недоступен."
                )
                self.openai_config = None

        if self.openai_config and not self.openai_config.validate():
            logger.warning("⚠️ Конфигурация OpenAI не валидна. Whisper-бэкенд будет отключён.")
            self.openai_config = None

        if deepseek_config is None:
            deepseek_config = DeepSeekConfig.from_file()

        if not deepseek_config.validate():
            raise ValueError("Некорректная конфигурация DeepSeek")

        self.deepseek_config = deepseek_config

        if fireworks_config is None:
            fireworks_config = FireworksConfig.from_file()

        if not fireworks_config.validate():
            raise ValueError("Некорректная конфигурация Fireworks")

        self.fireworks_config = fireworks_config

        self.whisper_service = WhisperService(self.openai_config) if self.openai_config else None
        self.fireworks_service = FireworksTranscriptionService(self.fireworks_config)
        self.topic_extractor = TopicExtractor(self.deepseek_config)

        target_bitrate = self.fireworks_config.audio_bitrate
        target_sample_rate = self.fireworks_config.audio_sample_rate
        max_file_size_mb = self.fireworks_config.max_file_size_mb

        if self.openai_config:
            # Используем минимальные ограничения, чтобы файл подходил для обеих моделей
            target_sample_rate = self.openai_config.audio_sample_rate or target_sample_rate
            target_bitrate = self.openai_config.audio_bitrate or target_bitrate
            max_file_size_mb = min(self.openai_config.max_file_size_mb, max_file_size_mb)

        self.audio_compressor = AudioCompressor(
            target_bitrate=target_bitrate,
            target_sample_rate=target_sample_rate,
            max_file_size_mb=max_file_size_mb,
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

    async def _transcribe_with_provider(
        self,
        audio_path: str,
        provider: TranscriptionProvider,
        language: str,
        audio_duration: float | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Транскрибация аудио выбранным бэкендом."""
        if provider == "fireworks":
            return await self.fireworks_service.transcribe_audio(
                audio_path=audio_path,
                language=language,
                audio_duration=audio_duration,
                prompt=prompt,
            )
        if provider == "whisper":
            if not self.whisper_service:
                raise RuntimeError(
                    "Whisper-бэкенд недоступен: отсутствует валидная конфигурация OpenAI."
                )
            return await self.whisper_service.transcribe_audio(
                audio_path=audio_path,
                language=language,
                audio_duration=audio_duration,
            )

        raise ValueError(f"Неизвестный провайдер транскрибации: {provider}")

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
        provider: TranscriptionProvider = "fireworks",
        granularity: str = "long",  # "short" | "long"
    ) -> dict[str, Any]:
        """
        Полная обработка аудио: сжатие, транскрибация, извлечение тем.

        Args:
            audio_path: Путь к аудио файлу
            recording_id: ID записи (для именования файлов)
            recording_topic: Название записи (для именования файлов)

        provider:
            Какой бэкенд использовать для транскрибации: "fireworks" (по умолчанию) или "whisper"

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

        logger.info(
            f"🎬 Начало обработки аудио: {audio_path} "
            f"(модель транскрибации: {provider})"
        )

        fireworks_prompt = None
        if provider == "fireworks":
            fireworks_prompt = self._compose_fireworks_prompt(recording_topic)

        # Шаг 1: Подготовка аудио (сжатие и разбиение, если нужно)
        prepared_audio, temp_files_to_cleanup = await self._prepare_audio(audio_path, provider=provider)
        transcription_language = (
            self.fireworks_config.language if provider == "fireworks" else "ru"
        )

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
                        result = await self._transcribe_with_provider(
                            audio_path=part_path,
                            provider=provider,
                            language=transcription_language,
                            audio_duration=part_duration,
                            prompt=fireworks_prompt,
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

                # Создаем задачи с небольшой задержкой между запусками, чтобы избежать rate limiting
                # Запускаем задачи не все сразу, а с небольшой задержкой (0.5 сек между запросами)
                transcription_tasks = []
                for i, part_path in enumerate(audio_files):
                    # Добавляем небольшую задержку между запусками параллельных запросов
                    # чтобы не отправлять все запросы одновременно (может вызвать rate limiting)
                    if i > 0:
                        await asyncio.sleep(0.5)  # 0.5 секунды задержка между запросами
                    task = asyncio.create_task(
                        transcribe_part_with_logging(i, part_path, part_durations[i])
                    )
                    transcription_tasks.append(task)

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
                transcription_result = await self._transcribe_with_provider(
                    audio_path=prepared_audio,
                    provider=provider,
                    language=transcription_language,
                    prompt=fireworks_prompt,
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

            # Преобразуем паузы в формат временных меток
            topic_timestamps = topics_result.get('topic_timestamps', [])
            long_pauses = topics_result.get('long_pauses', [])

            # Проверяем, какие перерывы уже есть в topic_timestamps (добавленные моделью)
            existing_pause_starts = set()
            for ts in topic_timestamps:
                topic = ts.get('topic', '').strip()
                # Проверяем, является ли это перерывом (с учетом разных вариантов написания)
                if topic.lower() in ['перерыв', 'pause', 'break']:
                    existing_pause_starts.add(ts.get('start', 0))

            # Добавляем паузы как отдельные временные метки, исключая дубликаты
            pause_timestamps = []
            for pause in long_pauses:
                pause_start = pause['start']
                # Пропускаем паузы, которые уже добавлены моделью
                # Используем небольшой допуск (5 секунд) для учета возможных расхождений во времени
                if not any(abs(pause_start - existing_start) < 5.0 for existing_start in existing_pause_starts):
                    pause_timestamps.append({
                        'topic': 'Перерыв',
                        'start': pause_start,
                        'end': pause['end'],
                        'type': 'pause',
                        'duration_minutes': pause.get('duration_minutes', (pause['end'] - pause_start) / 60),
                    })

            # Объединяем темы и паузы, сортируем по времени начала
            all_timestamps = topic_timestamps + pause_timestamps
            all_timestamps.sort(key=lambda x: x.get('start', 0))

            # Формируем результат
            result = {
                'transcription_file_path': transcription_file_path,
                'transcription_text': transcription_text,
                'topic_timestamps': all_timestamps,
                'main_topics': topics_result.get('main_topics', []),
                'long_pauses': long_pauses,  # Сохраняем также исходные данные о паузах
                'language': transcription_language,
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

    async def _prepare_audio(
        self, audio_path: str, provider: TranscriptionProvider = "fireworks"
    ) -> tuple[str | list[str], list[str]]:
        """
        Подготовка аудио: сжатие и разбиение, если нужно.
        Может работать как с аудио, так и с видео файлами (извлекает аудио автоматически).

        Args:
            audio_path: Путь к аудио файлу
            provider: Провайдер транскрибации ("fireworks" или "whisper")

        Returns:
            Tuple: (путь к файлу или список путей к частям, список временных файлов для удаления)
        """
        file_size = os.path.getsize(audio_path)
        file_size_mb = file_size / (1024 * 1024)
        temp_files = []

        # Для Fireworks не разбиваем файлы, так как API поддерживает большие файлы
        if provider == "fireworks":
            logger.info(
                f"🎆 Fireworks поддерживает большие файлы, разбиение не требуется "
                f"({file_size_mb:.2f} МБ)"
            )
            # Для Fireworks все равно может потребоваться сжатие/извлечение аудио из видео
            # но разбиение на части не нужно

        # Для Fireworks просто возвращаем файл как есть (без разбиения)
        if provider == "fireworks":
            # Проверяем, является ли файл видео (нужно извлечь аудио)
            is_video = audio_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'))
            if is_video:
                logger.info("🎬 Обнаружен видео файл, извлечение аудио для Fireworks...")
                # Извлекаем аудио из видео (но не разбиваем)
                compressed_path = await self.audio_compressor.compress_audio(audio_path)
                temp_files.append(compressed_path)
                return compressed_path, [compressed_path]
            # Если это уже аудио файл, возвращаем как есть
            return audio_path, []

        # Для Whisper - стандартная логика с разбиением
        # Проверяем, является ли файл видео (нужно всегда извлекать аудио)
        is_video = audio_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v'))

        # Если файл видео, всегда извлекаем аудио (даже если маленький)
        if is_video:
            logger.info("🎬 Обнаружен видео файл, извлечение аудио...")

        # Проверяем параметры аудио файла, чтобы понять, нужно ли сжатие
        # Если файл уже имеет оптимальные параметры (64k, 16kHz, моно) и достаточно мал, сжатие не требуется
        if not is_video:
            try:
                audio_info = await self.audio_compressor.get_audio_info(audio_path)
                # Проверяем параметры аудио
                sample_rate = audio_info.get('sample_rate', 0)
                bitrate = audio_info.get('bitrate', 0)
                channels = audio_info.get('channels', 0)

                # Если аудио уже имеет оптимальные параметры для Whisper (64k битрейт, 16kHz, моно)
                # и размер меньше лимита, сжатие не требуется
                optimal_bitrate = 64000  # 64k в битах в секунду
                optimal_sample_rate = 16000
                optimal_channels = 1

                # Проверяем, что параметры близки к оптимальным (с допуском)
                bitrate_ok = abs(bitrate - optimal_bitrate) < optimal_bitrate * 0.2  # ±20%
                sample_rate_ok = sample_rate == optimal_sample_rate
                channels_ok = channels == optimal_channels

                if bitrate_ok and sample_rate_ok and channels_ok:
                    logger.info(
                        f"✅ Аудио файл уже имеет оптимальные параметры для Whisper "
                        f"(битрейт: {bitrate/1000:.0f}k, частота: {sample_rate}Hz, каналы: {channels})"
                    )
                    # Если файл маленький, сжатие не требуется
                    if file_size_mb < self.openai_config.max_file_size_mb * 0.8:
                        logger.info(f"✅ Аудио файл уже достаточно мал ({file_size_mb:.2f} МБ), сжатие не требуется")
                        return audio_path, []
                    # Если файл большой, но параметры оптимальные, нужно только разбить на части
                    # Сжатие не требуется, так как параметры уже оптимальные
                    logger.info(
                        f"📊 Файл имеет оптимальные параметры, но большой размер ({file_size_mb:.2f} МБ). "
                        f"Пропускаем сжатие, сразу разбиваем на части."
                    )
                    # Разбиваем файл на части без предварительного сжатия
                    parts = await self.audio_compressor.split_audio(
                        audio_path, max_size_mb=self.openai_config.max_file_size_mb * 0.96
                    )
                    return parts, parts  # Возвращаем части и список для удаления (части)
            except Exception as e:
                logger.warning(f"⚠️ Не удалось проверить параметры аудио: {e}, продолжаем со сжатием")

        # Сжимаем аудио (если параметры не оптимальные)
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
                    start_time = seg.get('start', 0) or 0.0
                    end_time = seg.get('end', 0) or 0.0
                    text = seg.get('text', '').strip()

                    if text:
                        # Используем floor/ceil, чтобы визуальные метки не сжимались до одного значения
                        start_seconds = int(math.floor(float(start_time)))
                        end_seconds = int(math.ceil(float(end_time)))

                        if end_seconds <= start_seconds:
                            end_seconds = start_seconds + 1

                        # Форматируем временные метки
                        start_formatted = self._format_timestamp(start_seconds)
                        end_formatted = self._format_timestamp(end_seconds)

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

