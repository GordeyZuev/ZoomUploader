"""Celery tasks для обработки записей с multi-tenancy support."""

import asyncio
from pathlib import Path

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from api.celery_app import celery_app
from api.repositories.recording_repos import RecordingAsyncRepository
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from logger import get_logger
from models import MeetingRecording, ProcessingStageType, ProcessingStatus
from video_download_module.downloader import ZoomDownloader
from video_processing_module.video_processor import VideoProcessor

logger = get_logger()


class ProcessingTask(Task):
    """Базовый класс для задач обработки с multi-tenancy."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Обработка ошибки задачи."""
        user_id = kwargs.get("user_id", "unknown")
        recording_id = kwargs.get("recording_id", "unknown")
        logger.error(f"Task {task_id} for user {user_id}, recording {recording_id} failed: {exc!r}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Обработка повторной попытки."""
        user_id = kwargs.get("user_id", "unknown")
        logger.warning(f"Task {task_id} for user {user_id} retrying: {exc}")

    def on_success(self, retval, task_id, args, kwargs):
        """Обработка успешного завершения."""
        user_id = kwargs.get("user_id", "unknown")
        logger.info(f"Task {task_id} for user {user_id} completed successfully")


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.download_recording",
    max_retries=3,
    default_retry_delay=600,
)
def download_recording_task(
    self,
    recording_id: int,
    user_id: int,
    force: bool = False,
) -> dict:
    """
    Скачать запись из Zoom.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        force: Пересохранить если уже скачано

    Returns:
        Результат скачивания
    """
    try:
        logger.info(f"[Task {self.request.id}] Downloading recording {recording_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing download...', 'step': 'download'}
        )

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            _async_download_recording(self, recording_id, user_id, force)
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "result": result,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded")
        raise self.retry(countdown=900, exc=SoftTimeLimitExceeded())

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error downloading: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_download_recording(task_self, recording_id: int, user_id: int, force: bool) -> dict:
    """Async функция для скачивания."""
    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        recording_repo = RecordingAsyncRepository(session)

        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        # Проверяем download_url
        download_url = None
        if recording.source and recording.source.meta:
            download_url = recording.source.meta.get("download_url")

        if not download_url:
            raise ValueError("No download URL available. Please sync from Zoom first.")

        # Проверяем, что не скачано уже
        if not force and recording.status == ProcessingStatus.DOWNLOADED and recording.local_video_path:
            if Path(recording.local_video_path).exists():
                return {
                    "success": True,
                    "message": "Already downloaded",
                    "local_video_path": recording.local_video_path,
                }

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 30, 'status': 'Downloading from Zoom...', 'step': 'download'}
        )

        # Создаем downloader
        user_download_dir = f"media/user_{user_id}/video/unprocessed"
        downloader = ZoomDownloader(download_dir=user_download_dir)

        # Преобразуем в MeetingRecording
        meeting_id = recording.source.source_key if recording.source else str(recording.id)
        file_size = recording.source.meta.get("file_size", 0) if recording.source and recording.source.meta else 0
        download_access_token = recording.source.meta.get("download_access_token") if recording.source and recording.source.meta else None
        passcode = recording.source.meta.get("recording_play_passcode") if recording.source and recording.source.meta else None
        password = recording.source.meta.get("password") if recording.source and recording.source.meta else None
        account = recording.source.meta.get("account") if recording.source and recording.source.meta else None

        meeting_recording = MeetingRecording({
            "id": meeting_id,
            "uuid": meeting_id,
            "topic": recording.display_name,
            "start_time": recording.start_time.isoformat(),
            "duration": recording.duration or 0,
            "account": account or "default",
            "recording_files": [{
                "file_type": "MP4",
                "file_size": file_size,
                "download_url": download_url,
                "recording_type": "shared_screen_with_speaker_view",
                "download_access_token": download_access_token,
            }],
            "password": password,
            "recording_play_passcode": passcode,
        })
        meeting_recording.db_id = recording.id

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 50, 'status': 'Saving video file...', 'step': 'download'}
        )

        # Скачиваем
        success = await downloader.download_recording(meeting_recording, force_download=force)

        if success:
            task_self.update_state(
                state='PROCESSING',
                meta={'progress': 90, 'status': 'Updating database...', 'step': 'download'}
            )

            recording.local_video_path = meeting_recording.local_video_path
            recording.status = ProcessingStatus.DOWNLOADED
            await recording_repo.update(recording)
            await session.commit()

            return {
                "success": True,
                "local_video_path": recording.local_video_path,
            }
        else:
            raise Exception("Download failed")


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.process_video",
    max_retries=2,
    default_retry_delay=300,
)
def process_video_task(
    self,
    recording_id: int,
    user_id: int,
    silence_threshold: float = -40.0,
    min_silence_duration: float = 2.0,
    padding_before: float = 5.0,
    padding_after: float = 5.0,
) -> dict:
    """
    Обработать видео (FFmpeg - удаление тишины).

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        silence_threshold: Порог тишины в дБ
        min_silence_duration: Минимальная длительность тишины
        padding_before: Отступ до звука
        padding_after: Отступ после звука

    Returns:
        Результат обработки
    """
    try:
        logger.info(f"[Task {self.request.id}] Processing video {recording_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing video processing...', 'step': 'process'}
        )

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            _async_process_video(
                self,
                recording_id,
                user_id,
                silence_threshold,
                min_silence_duration,
                padding_before,
                padding_after,
            )
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "result": result,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded")
        raise self.retry(countdown=600, exc=SoftTimeLimitExceeded())

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error processing: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_process_video(
    task_self,
    recording_id: int,
    user_id: int,
    silence_threshold: float,
    min_silence_duration: float,
    padding_before: float,
    padding_after: float,
) -> dict:
    """Async функция для обработки видео."""
    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        recording_repo = RecordingAsyncRepository(session)

        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        if not recording.local_video_path:
            raise ValueError("No video file available. Please download first.")

        if not Path(recording.local_video_path).exists():
            raise ValueError(f"Video file not found: {recording.local_video_path}")

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 20, 'status': 'Analyzing video...', 'step': 'process'}
        )

        # Создаем processor с ProcessingConfig
        from video_processing_module.config import ProcessingConfig

        user_processed_dir = f"media/user_{user_id}/video/processed"
        config = ProcessingConfig(
            silence_threshold=silence_threshold,
            min_silence_duration=min_silence_duration,
            padding_before=padding_before,
            padding_after=padding_after,
            output_dir=user_processed_dir,
        )
        processor = VideoProcessor(config)

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 40, 'status': 'Processing with FFmpeg...', 'step': 'process'}
        )

        # Обрабатываем видео с детекцией звука
        success, processed_path = await processor.process_video_with_audio_detection(
            video_path=recording.local_video_path,
            title=recording.display_name,
            start_time=recording.start_time.isoformat(),
        )

        if success and processed_path:
            task_self.update_state(
                state='PROCESSING',
                meta={'progress': 60, 'status': 'Extracting audio from processed video...', 'step': 'extract_audio'}
            )

            # Извлекаем аудио из обработанного видео
            import subprocess

            from utils.file_utils import sanitize_filename

            audio_dir = f"media/user_{user_id}/audio/processed"
            Path(audio_dir).mkdir(parents=True, exist_ok=True)

            # Генерируем имя файла как в старой реализации
            safe_title = sanitize_filename(recording.display_name)
            date_suffix = ""
            try:
                date_obj = recording.start_time
                date_suffix = f"_{date_obj.strftime('%y-%m-%d_%H-%M')}"
            except Exception as e:
                logger.warning(f"⚠️ Ошибка форматирования даты для аудио: {e}")

            audio_filename = f"{safe_title}{date_suffix}_processed.mp3"
            audio_path = str(Path(audio_dir) / audio_filename)

            logger.info(f"🎵 Извлечение аудио из обработанного видео: {recording.display_name}")

            # FFmpeg команда для извлечения аудио (64k, 16kHz, mono)
            extract_cmd = [
                "ffmpeg",
                "-i", processed_path,
                "-vn",  # без видео
                "-acodec", "libmp3lame",
                "-ab", "64k",
                "-ar", "16000",
                "-ac", "1",  # mono
                "-y",  # перезаписать если существует
                audio_path,
            ]

            try:
                extract_process = await asyncio.create_subprocess_exec(
                    *extract_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stdout, stderr = await extract_process.communicate()

                if extract_process.returncode == 0 and Path(audio_path).exists():
                    recording.processed_audio_dir = audio_dir
                    logger.info(f"✅ Аудио извлечено: {audio_path}")
                else:
                    logger.warning(f"⚠️ Не удалось извлечь аудио: {stderr.decode()}")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при извлечении аудио: {e}")

            task_self.update_state(
                state='PROCESSING',
                meta={'progress': 90, 'status': 'Updating database...', 'step': 'process'}
            )

            recording.processed_video_path = processed_path
            recording.status = ProcessingStatus.PROCESSED
            # VIDEO_PROCESSING - это часть общего ProcessingStatus.PROCESSED, не детализируем
            await recording_repo.update(recording)
            await session.commit()

            return {
                "success": True,
                "processed_video_path": processed_path,
                "audio_path": audio_path if Path(audio_path).exists() else None,
            }
        else:
            raise Exception("Processing failed")


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.transcribe_recording",
    max_retries=2,
    default_retry_delay=300,
)
def transcribe_recording_task(
    self,
    recording_id: int,
    user_id: int,
) -> dict:
    """
    Транскрибация записи с АДМИНСКИМИ кредами.

    ВАЖНО: Только транскрибация (Fireworks), БЕЗ извлечения тем.
    Для извлечения тем используйте extract_topics_task.

    Args:
        recording_id: ID записи
        user_id: ID пользователя

    Returns:
        Результаты транскрибации (без топиков)
    """
    try:
        logger.info(f"[Task {self.request.id}] Transcribing recording {recording_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing transcription...', 'step': 'transcribe'}
        )

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            _async_transcribe_recording(self, recording_id, user_id)
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "result": result,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded")
        raise self.retry(countdown=600, exc=SoftTimeLimitExceeded())

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error transcribing: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_transcribe_recording(task_self, recording_id: int, user_id: int) -> dict:
    """
    Async функция для транскрибации с АДМИНСКИМИ КРЕДАМИ.

    ВАЖНО: Только транскрибация (Fireworks), без извлечения тем.
    Извлечение тем делается отдельно через /topics endpoint.
    """
    from fireworks_module import FireworksConfig, FireworksTranscriptionService
    from transcription_module.manager import get_transcription_manager

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        recording_repo = RecordingAsyncRepository(session)

        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        # Приоритет: обработанное аудио > обработанное видео > оригинальное видео
        audio_path = None

        # 1. Ищем обработанный аудио файл
        if recording.processed_audio_dir:
            audio_dir = Path(recording.processed_audio_dir)
            if audio_dir.exists():
                for ext in ("*.mp3", "*.wav", "*.m4a"):
                    audio_files = sorted(audio_dir.glob(ext))
                    if audio_files:
                        audio_path = str(audio_files[0])
                        logger.info(f"🎵 Используем обработанное аудио: {audio_path}")
                        break

        # 2. Fallback на обработанное или оригинальное видео
        if not audio_path:
            audio_path = recording.processed_video_path or recording.local_video_path
            if audio_path:
                logger.info(f"🎬 Используем видео файл (аудио не найдено): {audio_path}")

        if not audio_path:
            raise ValueError("No audio or video file available for transcription")

        if not Path(audio_path).exists():
            raise ValueError(f"Audio/video file not found: {audio_path}")

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 20, 'status': 'Loading transcription service...', 'step': 'transcribe'}
        )

        # Загружаем АДМИНСКИЕ креды (только Fireworks)
        fireworks_config = FireworksConfig.from_file("config/fireworks_creds.json")
        fireworks_service = FireworksTranscriptionService(fireworks_config)

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 30, 'status': 'Transcribing audio...', 'step': 'transcribe'}
        )

        # Формируем промпт для Fireworks
        from transcription_module.service import TranscriptionService

        fireworks_prompt = TranscriptionService._compose_fireworks_prompt(
            fireworks_config.prompt, recording.display_name
        )

        # Транскрибация через Fireworks API (ТОЛЬКО транскрибация, без извлечения тем)
        transcription_result = await fireworks_service.transcribe_audio(
            audio_path=audio_path,
            language=fireworks_config.language,
            prompt=fireworks_prompt,
        )

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 70, 'status': 'Saving transcription...', 'step': 'transcribe'}
        )

        # Сохраняем только master.json (БЕЗ topics.json)
        transcription_manager = get_transcription_manager()
        transcription_dir = transcription_manager.get_dir(recording_id)

        # Подготавливаем данные
        words = transcription_result.get("words", [])
        segments = transcription_result.get("segments", [])
        language = transcription_result.get("language", "ru")

        # Вычисляем длительность из последнего сегмента
        duration = 0.0
        if segments and len(segments) > 0:
            last_segment = segments[-1]
            duration = last_segment.get("end", 0.0)

        # Собираем метаданные для админа (для расчета стоимости)
        usage_metadata = {
            "model": fireworks_config.model,
            "prompt_used": fireworks_prompt,
            "config": {
                "temperature": fireworks_config.temperature,
                "language": fireworks_config.language,
                "response_format": fireworks_config.response_format,
                "timestamp_granularities": fireworks_config.timestamp_granularities,
                "preprocessing": fireworks_config.preprocessing,
            },
            "audio_file": {
                "path": audio_path,
                "duration_seconds": duration,
            },
            # Если Fireworks API возвращает usage, добавляем сюда
            "usage": transcription_result.get("usage"),
        }

        # Сохраняем master.json
        transcription_manager.save_master(
            recording_id=recording_id,
            words=words,
            segments=segments,
            language=language,
            model="fireworks",
            duration=duration,
            usage_metadata=usage_metadata,
            user_id=user_id,
            raw_response=transcription_result,
        )

        # Генерируем кэш-файлы (segments.txt, words.txt)
        transcription_manager.generate_cache_files(recording_id, user_id=user_id)

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 90, 'status': 'Updating database...', 'step': 'transcribe'}
        )

        # Обновляем запись в БД (без топиков)
        recording.transcription_dir = str(transcription_dir)
        recording.transcription_info = transcription_result

        # Помечаем этап транскрибации как завершённый
        recording.mark_stage_completed(
            ProcessingStageType.TRANSCRIBE,
            meta={"transcription_dir": str(transcription_dir), "language": language, "model": "fireworks"},
        )

        # Обновляем агрегированный статус на основе processing_stages
        from api.helpers.status_manager import update_aggregate_status
        update_aggregate_status(recording)

        await recording_repo.update(recording)
        await session.commit()

        logger.info(
            f"✅ Transcription completed for recording {recording_id}: "
            f"words={len(words)}, segments={len(segments)}, language={language}"
        )

        return {
            "success": True,
            "transcription_dir": str(transcription_dir),
            "language": language,
            "words_count": len(words),
            "segments_count": len(segments),
        }


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.full_pipeline",
    max_retries=1,
    default_retry_delay=600,
)
def full_pipeline_task(
    self,
    recording_id: int,
    user_id: int,
    download: bool = True,
    process: bool = True,
    transcribe: bool = True,
    upload: bool = False,
    platforms: list[str] | None = None,
    preset_ids: dict[str, int] | None = None,
    granularity: str = "long",
    process_config: dict | None = None,
) -> dict:
    """
    Полный пайплайн обработки: download → process → transcribe → upload.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        download: Выполнить download
        process: Выполнить process
        transcribe: Выполнить transcribe
        upload: Выполнить upload
        platforms: Список платформ для загрузки
        preset_ids: Словарь {platform: preset_id}
        granularity: Режим извлечения тем
        process_config: Конфигурация обработки видео

    Returns:
        Результаты полного пайплайна
    """
    try:
        logger.info(f"[Task {self.request.id}] Full pipeline for recording {recording_id}, user {user_id}")

        from api.tasks.upload import upload_recording_to_platform

        platforms = platforms or []
        process_config = process_config or {}

        results = {
            "recording_id": recording_id,
            "steps_completed": [],
            "errors": [],
        }

        total_steps = sum([download, process, transcribe, upload and len(platforms) > 0])
        current_step = 0

        # STEP 1: Download
        if download:
            try:
                self.update_state(
                    state='PROCESSING',
                    meta={
                        'progress': int((current_step / total_steps) * 100),
                        'status': 'Downloading from Zoom...',
                        'step': 'download'
                    }
                )

                download_result = download_recording_task.apply(
                    args=[recording_id, user_id, False]
                ).get()

                results["steps_completed"].append("download")
                results["download"] = download_result["result"]
                current_step += 1
            except Exception as e:
                results["errors"].append(f"Download failed: {str(e)}")
                logger.error(f"Download step failed: {e}")

        # STEP 2: Process
        if process:
            try:
                self.update_state(
                    state='PROCESSING',
                    meta={
                        'progress': int((current_step / total_steps) * 100),
                        'status': 'Processing video...',
                        'step': 'process'
                    }
                )

                process_result = process_video_task.apply(
                    args=[recording_id, user_id],
                    kwargs=process_config,
                ).get()

                results["steps_completed"].append("process")
                results["process"] = process_result["result"]
                current_step += 1
            except Exception as e:
                results["errors"].append(f"Processing failed: {str(e)}")
                logger.error(f"Processing step failed: {e}")

        # STEP 3: Transcribe
        if transcribe:
            try:
                self.update_state(
                    state='PROCESSING',
                    meta={
                        'progress': int((current_step / total_steps) * 100),
                        'status': 'Transcribing...',
                        'step': 'transcribe'
                    }
                )

                transcribe_result = transcribe_recording_task.apply(
                    args=[recording_id, user_id]
                ).get()

                results["steps_completed"].append("transcribe")
                results["transcribe"] = transcribe_result["result"]
                current_step += 1
            except Exception as e:
                results["errors"].append(f"Transcription failed: {str(e)}")
                logger.error(f"Transcription step failed: {e}")

        # STEP 4: Upload
        if upload and platforms:
            upload_results = []
            for platform in platforms:
                try:
                    self.update_state(
                        state='PROCESSING',
                        meta={
                            'progress': int((current_step / total_steps) * 100),
                            'status': f'Uploading to {platform}...',
                            'step': 'upload'
                        }
                    )

                    preset_id = preset_ids.get(platform) if preset_ids else None

                    upload_result = upload_recording_to_platform.apply(
                        args=[recording_id, user_id, platform, preset_id]
                    ).get()

                    upload_results.append(upload_result["result"])
                except Exception as e:
                    results["errors"].append(f"Upload to {platform} failed: {str(e)}")
                    logger.error(f"Upload to {platform} failed: {e}")

            if upload_results:
                results["steps_completed"].append("upload")
                results["upload"] = upload_results
                current_step += 1

        # Финальный статус
        if not results["errors"]:
            results["status"] = "completed"
        elif results["steps_completed"]:
            results["status"] = "partially_completed"
        else:
            results["status"] = "failed"

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "result": results,
        }

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Full pipeline failed: {exc!r}", exc_info=True)
        raise


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.extract_topics",
    max_retries=2,
    default_retry_delay=300,
)
def extract_topics_task(
    self,
    recording_id: int,
    user_id: int,
    granularity: str = "long",
    version_id: str | None = None,
) -> dict:
    """
    Извлечь темы из существующей транскрибации (только админские креды).

    Модель выбирается автоматически с ретраями и фоллбэками:
    1. Сначала deepseek (основная модель)
    2. Fallback на fireworks_deepseek при ошибке

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        granularity: Режим извлечения ("short" | "long")
        version_id: ID версии (если None, генерируется автоматически)

    Returns:
        Результаты извлечения тем
    """
    try:
        logger.info(f"[Task {self.request.id}] Extracting topics for recording {recording_id}, user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing topic extraction...', 'step': 'extract_topics'}
        )

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            _async_extract_topics(self, recording_id, user_id, granularity, version_id)
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "result": result,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded")
        raise self.retry(countdown=600, exc=SoftTimeLimitExceeded())

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error extracting topics: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_extract_topics(
    task_self, recording_id: int, user_id: int, granularity: str, version_id: str | None
) -> dict:
    """
    Async функция для извлечения тем с автоматическим выбором модели.

    Стратегия:
    1. Попытка с deepseek (основная модель)
    2. Fallback на fireworks_deepseek при ошибке
    """
    from deepseek_module import DeepSeekConfig, TopicExtractor
    from transcription_module.manager import get_transcription_manager

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        recording_repo = RecordingAsyncRepository(session)

        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        # Проверяем наличие транскрибации
        transcription_manager = get_transcription_manager()
        if not transcription_manager.has_master(recording_id, user_id=user_id):
            raise ValueError(
                f"Transcription not found for recording {recording_id}. Please run transcription first."
            )

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 20, 'status': 'Loading transcription...', 'step': 'extract_topics'}
        )

        # Гарантируем наличие segments.txt
        segments_path = transcription_manager.ensure_segments_txt(recording_id, user_id=user_id)

        # Попытка извлечения тем с fallback стратегией
        topics_result = None
        model_used = None
        last_error = None

        # Стратегия 1: DeepSeek (основная модель)
        try:
            logger.info(f"[Topics] Trying primary model: deepseek for recording {recording_id}")
            task_self.update_state(
                state='PROCESSING',
                meta={'progress': 40, 'status': 'Extracting topics (deepseek)...', 'step': 'extract_topics'}
            )

            deepseek_config = DeepSeekConfig.from_file("config/deepseek_creds.json")
            topic_extractor = TopicExtractor(deepseek_config)

            topics_result = await topic_extractor.extract_topics_from_file(
                segments_file_path=str(segments_path),
                recording_topic=recording.display_name,
                granularity=granularity,
            )
            model_used = "deepseek"
            logger.info(f"[Topics] Successfully extracted with deepseek for recording {recording_id}")

        except Exception as e:
            logger.warning(f"[Topics] DeepSeek failed for recording {recording_id}: {e}. Trying fallback...")
            last_error = e

            # Стратегия 2: Fireworks DeepSeek (fallback)
            try:
                logger.info(f"[Topics] Trying fallback model: fireworks_deepseek for recording {recording_id}")
                task_self.update_state(
                    state='PROCESSING',
                    meta={'progress': 50, 'status': 'Extracting topics (fallback)...', 'step': 'extract_topics'}
                )

                deepseek_config = DeepSeekConfig.from_file("config/deepseek_fireworks_creds.json")
                topic_extractor = TopicExtractor(deepseek_config)

                topics_result = await topic_extractor.extract_topics_from_file(
                    segments_file_path=str(segments_path),
                    recording_topic=recording.display_name,
                    granularity=granularity,
                )
                model_used = "fireworks_deepseek"
                logger.info(f"[Topics] Successfully extracted with fireworks_deepseek for recording {recording_id}")

            except Exception as e2:
                logger.error(f"[Topics] All models failed for recording {recording_id}. Last error: {e2}")
                raise ValueError(f"Failed to extract topics with all models. Primary: {last_error}, Fallback: {e2}")

        if not topics_result:
            raise ValueError("Failed to extract topics: no result returned")

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 80, 'status': 'Saving topics...', 'step': 'extract_topics'}
        )

        # Генерируем version_id если не задан
        if not version_id:
            version_id = transcription_manager.generate_version_id(recording_id, user_id=user_id)

        # Собираем метаданные для админа
        usage_metadata = {
            "model": model_used,
            "prompt_used": "See TopicExtractor code for prompt generation",
            "config": {
                "temperature": deepseek_config.temperature if deepseek_config else None,
                "max_tokens": deepseek_config.max_tokens if deepseek_config else None,
            },
            # Здесь можно добавить usage из API response, если доступно
        }

        # Сохраняем в topics.json
        transcription_manager.add_topics_version(
            recording_id=recording_id,
            version_id=version_id,
            model=model_used,
            granularity=granularity,
            main_topics=topics_result.get("main_topics", []),
            topic_timestamps=topics_result.get("topic_timestamps", []),
            pauses=topics_result.get("long_pauses", []),
            is_active=True,
            usage_metadata=usage_metadata,
            user_id=user_id,
        )

        # Обновляем запись в БД (активная версия)
        recording.topic_timestamps = topics_result.get("topic_timestamps", [])
        recording.main_topics = topics_result.get("main_topics", [])

        # Помечаем этап извлечения тем как завершённый
        recording.mark_stage_completed(
            ProcessingStageType.EXTRACT_TOPICS,
            meta={"version_id": version_id, "granularity": granularity, "model": model_used},
        )

        # Обновляем агрегированный статус
        from api.helpers.status_manager import update_aggregate_status
        update_aggregate_status(recording)

        await recording_repo.update(recording)
        await session.commit()

        # Не показываем модель пользователю, только результаты
        return {
            "success": True,
            "version_id": version_id,
            "topics_count": len(topics_result.get("topic_timestamps", [])),
            "main_topics": topics_result.get("main_topics", []),
        }


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.generate_subtitles",
    max_retries=2,
    default_retry_delay=60,
)
def generate_subtitles_task(
    self,
    recording_id: int,
    user_id: int,
    formats: list[str] | None = None,
) -> dict:
    """
    Генерировать субтитры из существующей транскрибации.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        formats: Список форматов ('srt', 'vtt')

    Returns:
        Результаты генерации субтитров
    """
    try:
        logger.info(f"[Task {self.request.id}] Generating subtitles for recording {recording_id}, user {user_id}")

        formats = formats or ["srt", "vtt"]

        self.update_state(
            state='PROCESSING',
            meta={'progress': 20, 'status': 'Initializing subtitle generation...', 'step': 'generate_subtitles'}
        )

        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(
            _async_generate_subtitles(self, recording_id, user_id, formats)
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "result": result,
        }

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error generating subtitles: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_generate_subtitles(task_self, recording_id: int, user_id: int, formats: list[str]) -> dict:
    """Async функция для генерации субтитров."""
    from transcription_module.manager import get_transcription_manager

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        recording_repo = RecordingAsyncRepository(session)

        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        # Проверяем наличие транскрибации
        transcription_manager = get_transcription_manager()
        if not transcription_manager.has_master(recording_id, user_id=user_id):
            raise ValueError(
                f"Transcription not found for recording {recording_id}. Please run transcription first."
            )

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 40, 'status': 'Generating subtitles...', 'step': 'generate_subtitles'}
        )

        # Генерируем субтитры
        subtitle_paths = transcription_manager.generate_subtitles(
            recording_id=recording_id,
            formats=formats,
            user_id=user_id,
        )

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 90, 'status': 'Saving results...', 'step': 'generate_subtitles'}
        )

        # Обновляем запись в БД
        recording.mark_stage_completed(
            ProcessingStageType.GENERATE_SUBTITLES,
            meta={"formats": formats, "files": subtitle_paths},
        )

        # Обновляем агрегированный статус
        from api.helpers.status_manager import update_aggregate_status
        update_aggregate_status(recording)

        await recording_repo.update(recording)
        await session.commit()

        return {
            "success": True,
            "formats": formats,
            "files": subtitle_paths,
        }
