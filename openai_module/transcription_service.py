"""Сервис для транскрибации аудио через OpenAI Whisper API"""

import asyncio
import os
import time
from typing import Any

from openai import AsyncOpenAI

from logger import get_logger

from .config import OpenAIConfig

logger = get_logger()


class TranscriptionService:
    """Сервис для работы с Whisper API"""

    def __init__(self, config: OpenAIConfig):
        self.config = config
        # Базовый клиент создадим позже с динамическим timeout

    def _create_client(self, timeout: float) -> AsyncOpenAI:
        """Создание клиента OpenAI с указанным timeout"""
        from httpx import Timeout
        return AsyncOpenAI(
            api_key=self.config.api_key,
            timeout=Timeout(
                connect=30.0,  # Таймаут на подключение
                read=timeout,  # Таймаут на чтение (для больших файлов)
                write=60.0,  # Таймаут на запись (увеличен для больших файлов)
                pool=30.0,  # Таймаут на получение соединения из пула
            )
        )

    async def transcribe_audio(
        self, audio_path: str, language: str = "ru", audio_duration: float | None = None
    ) -> dict[str, Any]:
        """
        Транскрибация аудио файла через Whisper API.

        Args:
            audio_path: Путь к аудио файлу
            language: Язык аудио (по умолчанию 'ru' для русского)

        Returns:
            Словарь с результатами транскрибации:
            {
                'text': str,  # Полный текст транскрипции
                'segments': list,  # Сегменты с временными метками
                'language': str,  # Определенный язык
            }
        """
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Аудио файл не найден: {audio_path}")

        # Проверяем размер файла
        file_size = os.path.getsize(audio_path)
        file_size_mb = file_size / (1024 * 1024)

        if file_size_mb > self.config.max_file_size_mb:
            raise ValueError(
                f"Файл слишком большой: {file_size_mb:.2f} МБ > {self.config.max_file_size_mb} МБ"
            )

        start_time = time.time()

        # Динамически рассчитываем timeout на основе размера файла и длительности аудио
        # Если длительность известна, используем более точную оценку:
        # - Загрузка файла: ~1-2 минуты
        # - Обработка на сервере: примерно 0.1-0.2x от длительности аудио (Whisper работает быстро)
        # - Итого: ~0.15x длительности + 2 минуты на загрузку

        if audio_duration and audio_duration > 0:
            # Более точная оценка на основе длительности
            # Whisper обрабатывает примерно в 0.1-0.2x реального времени аудио
            processing_time_seconds = audio_duration * 0.15  # 15% от длительности на обработку (в секундах)
            upload_time_seconds = 2.0 * 60  # ~2 минуты на загрузку файла (в секундах)
            total_time_seconds = processing_time_seconds + upload_time_seconds
            estimated_minutes = max(5, int(total_time_seconds / 60))
            logger.debug(f"📊 Оценка на основе длительности: {audio_duration/60:.1f} мин аудио → ~{estimated_minutes} мин обработки (processing: {processing_time_seconds/60:.1f} мин, upload: {upload_time_seconds/60:.1f} мин)")
        else:
            # Fallback: оценка на основе размера файла (менее точно)
            # Примерно 1 МБ = 1-2 минуты обработки, минимум 5 минут для любого файла
            estimated_minutes = max(5, int(file_size_mb * 1.5))
            logger.debug(f"📊 Оценка на основе размера: {file_size_mb:.2f} МБ → ~{estimated_minutes} мин обработки")

        dynamic_timeout = max(self.config.timeout, estimated_minutes * 60 * 1.5)  # Запас 50%

        # Обновляем timeout клиента для этого запроса
        # (к сожалению, OpenAI SDK не позволяет менять timeout для отдельного запроса,
        # но мы можем логировать ожидаемое время)

        logger.info(
            f"🎤 Транскрибация аудио: {audio_path} ({file_size_mb:.2f} МБ)\n"
            f"   ⏱️  Ожидаемое время обработки: ~{estimated_minutes} минут\n"
            f"   ⏱️  Таймаут установлен: {self.config.timeout/60:.1f} минут "
            f"(рекомендуется {dynamic_timeout/60:.1f} минут для этого файла)"
        )

        # Используем динамический timeout для больших файлов
        actual_timeout = max(self.config.timeout, dynamic_timeout)

        # Предупреждение, если файл большой, а timeout был увеличен
        if actual_timeout > self.config.timeout:
            logger.info(
                f"💡 Таймаут увеличен до {actual_timeout/60:.1f} минут для файла {file_size_mb:.2f} МБ "
                f"(базовый: {self.config.timeout/60:.1f} минут)"
            )

        # Создаем клиент с нужным timeout
        client = self._create_client(actual_timeout)

        # Пробуем транскрибировать с повторными попытками
        last_error = None
        for attempt in range(1, self.config.retry_attempts + 1):
            try:
                if attempt > 1:
                    elapsed = time.time() - start_time
                    logger.info(
                        f"🔄 Повторная попытка {attempt}/{self.config.retry_attempts} "
                        f"(прошло {elapsed/60:.1f} минут)"
                    )
                    # Задержка перед повтором уже обрабатывается в блоке except
                    # Здесь не добавляем дополнительную задержку

                # Открываем файл и отправляем в API
                attempt_start = time.time()
                logger.info(f"📤 Начало загрузки файла в Whisper API (попытка {attempt})...")
                if audio_duration:
                    logger.info(f"   📊 Размер: {file_size_mb:.2f} МБ, длительность: {audio_duration/60:.1f} мин")
                else:
                    logger.info(f"   📊 Размер файла: {file_size_mb:.2f} МБ")

                # Оцениваем время загрузки (примерно 1-2 минуты на 20 МБ при хорошем соединении)
                estimated_upload_time = max(30, file_size_mb * 3)  # ~3 секунды на МБ, минимум 30 секунд
                logger.info(f"   ⏱️  Ожидаемое время загрузки: ~{estimated_upload_time/60:.1f} мин")

                # Засекаем время открытия файла
                file_open_start = time.time()
                audio_file = open(audio_path, 'rb')
                file_open_time = time.time() - file_open_start
                logger.debug(f"   📂 Файл открыт за {file_open_time:.2f} сек")

                try:
                    # Засекаем время начала API запроса (включает загрузку + обработку)
                    api_request_start = time.time()
                    logger.info("   🚀 Отправка запроса в API (начало загрузки файла на сервер)...")

                    # Создаем задачу для периодического логирования
                    async def log_progress():
                        """Периодическое логирование прогресса"""
                        check_interval = 30  # Проверяем каждые 30 секунд
                        elapsed = 0
                        while True:
                            await asyncio.sleep(check_interval)
                            elapsed += check_interval
                            logger.info(
                                f"   ⏳ Ожидание ответа от API... (прошло {elapsed/60:.1f} мин)"
                            )

                    # Запускаем задачу логирования прогресса
                    progress_task = asyncio.create_task(log_progress())

                    try:
                        transcript = await client.audio.transcriptions.create(
                            model=self.config.whisper_model,
                            file=audio_file,
                            language=language,
                            response_format="verbose_json",  # Получаем полный ответ с сегментами
                        )
                    finally:
                        # Останавливаем задачу логирования
                        progress_task.cancel()
                        try:
                            await progress_task
                        except asyncio.CancelledError:
                            pass

                    api_request_end = time.time()
                    api_total_time = api_request_end - api_request_start
                    logger.info(f"   ✅ Ответ получен от API за {api_total_time/60:.1f} мин ({api_total_time:.1f} сек)")

                    # Оцениваем время загрузки и обработки
                    # Загрузка обычно занимает 10-20% от общего времени для больших файлов
                    # Обработка - остальное время
                    estimated_upload_portion = min(0.3, estimated_upload_time / api_total_time) if api_total_time > estimated_upload_time else 0.5
                    estimated_upload_time_actual = api_total_time * estimated_upload_portion
                    estimated_processing_time = api_total_time - estimated_upload_time_actual

                    logger.info(
                        f"   📊 Разбивка времени (оценочная):\n"
                        f"      📤 Загрузка файла: ~{estimated_upload_time_actual/60:.1f} мин (~{estimated_upload_portion*100:.0f}%)\n"
                        f"      ⚙️  Обработка на сервере: ~{estimated_processing_time/60:.1f} мин (~{(1-estimated_upload_portion)*100:.0f}%)"
                    )
                finally:
                    audio_file.close()

                elapsed = time.time() - start_time
                attempt_elapsed = time.time() - attempt_start

                # Вычисляем ожидаемое время для сравнения
                if audio_duration:
                    efficiency = (audio_duration / api_total_time) if api_total_time > 0 else 0
                    time_ratio = api_total_time / audio_duration if audio_duration > 0 else 0

                    logger.info(
                        f"   📊 Эффективность: {efficiency:.1f}x реального времени "
                        f"(обработано {audio_duration/60:.1f} мин аудио за {api_total_time/60:.1f} мин, "
                        f"соотношение {time_ratio:.2f}, обычно ~0.10-0.20)"
                    )

                    # Предупреждение, если обработка заняла необычно долго
                    if time_ratio > 0.30:  # Больше 30% от длительности - подозрительно долго
                        logger.warning(
                            f"   ⚠️ Обработка заняла необычно долго: {api_total_time/60:.1f} мин для "
                            f"{audio_duration/60:.1f} мин аудио (соотношение {time_ratio:.2f}, обычно ~0.10-0.20). "
                            f"Возможные причины: задержка сети, очередь на сервере OpenAI, высокая нагрузка."
                        )
                else:
                    logger.info(
                        f"   ⏱️  Общее время попытки: {attempt_elapsed/60:.1f} мин"
                    )

                # Формируем результат
                result = {
                    'text': transcript.text,
                    'language': transcript.language,
                    'segments': [],
                }

                # Добавляем сегменты, если они есть
                if hasattr(transcript, 'segments') and transcript.segments:
                    result['segments'] = [
                        {
                            'id': seg.id,
                            'start': seg.start,
                            'end': seg.end,
                            'text': seg.text,
                        }
                        for seg in transcript.segments
                    ]

                return result

            except Exception as e:
                last_error = e
                elapsed = time.time() - start_time
                error_type = type(e).__name__
                error_str = str(e).lower()

                # Проверяем тип ошибки для выбора стратегии повтора
                is_connection_error = "connection" in error_str or "apiconnectionerror" in error_str
                is_timeout = "timeout" in error_str or "timed out" in error_str
                is_rate_limit = "rate limit" in error_str or "429" in error_str

                if is_timeout:
                    logger.warning(
                        f"⚠️ Таймаут при транскрибации (попытка {attempt}/{self.config.retry_attempts})\n"
                        f"   ⏱️  Прошло времени: {elapsed/60:.1f} минут\n"
                        f"   💡 Это может быть нормально для больших файлов. "
                        f"Текущий таймаут: {self.config.timeout/60:.1f} минут"
                    )
                    # Для таймаутов увеличиваем задержку перед повтором
                    if attempt < self.config.retry_attempts:
                        wait_time = self.config.retry_delay * (2 ** (attempt - 1))  # Экспоненциальная задержка
                        logger.info(f"   ⏳ Ожидание {wait_time:.1f} сек перед повтором...")
                        await asyncio.sleep(wait_time)
                elif is_connection_error:
                    logger.warning(
                        f"⚠️ Ошибка подключения при транскрибации (попытка {attempt}/{self.config.retry_attempts}): {error_type}\n"
                        f"   ⏱️  Прошло времени: {elapsed/60:.1f} минут\n"
                        f"   💡 Возможные причины: проблемы с сетью, rate limiting, перегрузка сервера"
                    )
                    # Для ошибок подключения используем экспоненциальную задержку
                    if attempt < self.config.retry_attempts:
                        wait_time = self.config.retry_delay * (2 ** (attempt - 1))  # 1с, 2с, 4с...
                        # Но не больше 30 секунд
                        wait_time = min(wait_time, 30.0)
                        logger.info(f"   ⏳ Ожидание {wait_time:.1f} сек перед повтором (экспоненциальная задержка)...")
                        await asyncio.sleep(wait_time)
                elif is_rate_limit:
                    logger.warning(
                        f"⚠️ Rate limit при транскрибации (попытка {attempt}/{self.config.retry_attempts}): {error_type}\n"
                        f"   ⏱️  Прошло времени: {elapsed/60:.1f} минут\n"
                        f"   💡 Превышен лимит запросов к API, увеличиваем задержку"
                    )
                    # Для rate limit используем большую задержку
                    if attempt < self.config.retry_attempts:
                        wait_time = 10.0 * attempt  # 10с, 20с, 30с...
                        logger.info(f"   ⏳ Ожидание {wait_time:.1f} сек перед повтором (rate limit)...")
                        await asyncio.sleep(wait_time)
                else:
                    logger.warning(
                        f"⚠️ Ошибка транскрибации (попытка {attempt}/{self.config.retry_attempts}): {error_type}: {e}\n"
                        f"   ⏱️  Прошло времени: {elapsed/60:.1f} минут"
                    )
                    # Для других ошибок используем стандартную задержку
                    if attempt < self.config.retry_attempts:
                        wait_time = self.config.retry_delay * attempt
                        await asyncio.sleep(wait_time)

        # Если все попытки неудачны
        logger.error(f"❌ Не удалось транскрибировать аудио после {self.config.retry_attempts} попыток")
        raise RuntimeError(
            f"Ошибка транскрибации после {self.config.retry_attempts} попыток: {last_error}"
        ) from last_error

