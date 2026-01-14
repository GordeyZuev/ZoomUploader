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
    manual_override: dict | None = None,
) -> dict:
    """
    Скачать запись из Zoom (template-driven).

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        force: Пересохранить если уже скачано
        manual_override: Опциональное переопределение конфигурации

    Returns:
        Результат скачивания
    """
    try:
        logger.info(f"[Task {self.request.id}] Downloading recording {recording_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing download...', 'step': 'download'}
        )

        result = asyncio.run(
            _async_download_recording(self, recording_id, user_id, force, manual_override)
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


async def _async_download_recording(
    task_self,
    recording_id: int,
    user_id: int,
    force: bool,
    manual_override: dict | None = None,
) -> dict:
    """Async функция для скачивания (template-driven)."""
    from api.helpers.config_resolution_helper import resolve_full_config

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        # Resolve config
        full_config, recording = await resolve_full_config(
            session, recording_id, user_id, manual_override
        )

        download_config = full_config.get("download", {})

        # Extract download parameters
        max_file_size_mb = download_config.get("max_file_size_mb", 5000)
        retry_attempts = download_config.get("retry_attempts", 3)

        logger.debug(
            f"Download config for recording {recording_id}: "
            f"max_file_size_mb={max_file_size_mb}, retry_attempts={retry_attempts}"
        )

        recording_repo = RecordingAsyncRepository(session)

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
    name="api.tasks.processing.trim_video",
    max_retries=2,
    default_retry_delay=300,
)
def trim_video_task(
    self,
    recording_id: int,
    user_id: int,
    manual_override: dict | None = None,
) -> dict:
    """
    Обрезать видео - FFmpeg (удаление тишины, template-driven).

    Параметры берутся из resolved config (user_config < template < manual_override):
    - processing.silence_threshold
    - processing.min_silence_duration
    - processing.padding_before
    - processing.padding_after

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        manual_override: Опциональное переопределение конфигурации

    Returns:
        Результат обработки
    """
    try:
        logger.info(f"[Task {self.request.id}] Trimming video {recording_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing video trimming...', 'step': 'trim'}
        )

        result = asyncio.run(
            _async_process_video(self, recording_id, user_id, manual_override)
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
    manual_override: dict | None = None,
) -> dict:
    """Async функция для обработки видео (template-driven)."""
    from api.helpers.config_resolution_helper import resolve_full_config

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        # Resolve config from hierarchy
        full_config, recording = await resolve_full_config(
            session, recording_id, user_id, manual_override
        )

        processing_config = full_config.get("processing", {})

        # Extract processing parameters
        silence_threshold = processing_config.get("silence_threshold", -40.0)
        min_silence_duration = processing_config.get("min_silence_duration", 2.0)
        padding_before = processing_config.get("padding_before", 5.0)
        padding_after = processing_config.get("padding_after", 5.0)

        logger.debug(
            f"Processing config for recording {recording_id}: "
            f"silence_threshold={silence_threshold}, min_silence_duration={min_silence_duration}"
        )

        recording_repo = RecordingAsyncRepository(session)

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
                    recording.processed_audio_path = str(audio_path)
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
    manual_override: dict | None = None,
) -> dict:
    """
    Транскрибация записи с АДМИНСКИМИ кредами (template-driven).

    ВАЖНО: Только транскрибация (Fireworks), БЕЗ извлечения тем.
    Для извлечения тем используйте extract_topics_task.

    Config parameters used:
    - transcription.language (default: "ru")
    - transcription.prompt (default: "")
    - transcription.temperature (default: 0.0)

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        manual_override: Опциональное переопределение конфигурации

    Returns:
        Результаты транскрибации (без топиков)
    """
    try:
        logger.info(f"[Task {self.request.id}] Transcribing recording {recording_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Initializing transcription...', 'step': 'transcribe'}
        )

        result = asyncio.run(
            _async_transcribe_recording(self, recording_id, user_id, manual_override)
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


async def _async_transcribe_recording(
    task_self,
    recording_id: int,
    user_id: int,
    manual_override: dict | None = None,
) -> dict:
    """
    Async функция для транскрибации с АДМИНСКИМИ КРЕДАМИ (template-driven).

    ВАЖНО: Только транскрибация (Fireworks), без извлечения тем.
    Извлечение тем делается отдельно через /topics endpoint.

    Config parameters used:
    - transcription.language (default: "ru")
    - transcription.prompt (default: "")
    - transcription.temperature (default: 0.0)
    """
    from api.helpers.config_resolution_helper import resolve_full_config
    from fireworks_module import FireworksConfig, FireworksTranscriptionService
    from transcription_module.manager import get_transcription_manager

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        # Resolve config from hierarchy
        full_config, recording = await resolve_full_config(
            session, recording_id, user_id, manual_override
        )

        transcription_config = full_config.get("transcription", {})

        # Extract transcription parameters
        language = transcription_config.get("language", "ru")
        user_prompt = transcription_config.get("prompt", "")
        temperature = transcription_config.get("temperature", 0.0)

        logger.debug(
            f"Transcription config for recording {recording_id}: "
            f"language={language}, has_prompt={bool(user_prompt)}, temperature={temperature}"
        )

        recording_repo = RecordingAsyncRepository(session)

        # Приоритет: обработанное аудио > обработанное видео > оригинальное видео
        audio_path = None

        # 1. Используем сохраненный путь к аудиофайлу
        if recording.processed_audio_path:
            audio_path = Path(recording.processed_audio_path)
            if audio_path.exists():
                audio_files = [audio_path]
            else:
                audio_files = []
        else:
            # Fallback: ищем в директории (для старых записей без processed_audio_path)
            audio_dir = Path(recording.transcription_dir).parent.parent / "audio" / "processed" if recording.transcription_dir else None
            audio_files = []
            if audio_dir and audio_dir.exists():
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

        # Формируем промпт: user_prompt (из config) + display_name
        from transcription_module.service import TranscriptionService

        fireworks_prompt = TranscriptionService._compose_fireworks_prompt(
            user_prompt, recording.display_name
        )

        # Транскрибация через Fireworks API (ТОЛЬКО транскрибация, без извлечения тем)
        # Используем language и temperature из resolved config
        transcription_result = await fireworks_service.transcribe_audio(
            audio_path=audio_path,
            language=language,  # ← from resolved config
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
        detected_language = transcription_result.get("language", language)

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
                "temperature": temperature,  # ← from resolved config
                "language": language,  # ← from resolved config
                "detected_language": detected_language,
                "response_format": fireworks_config.response_format,
                "timestamp_granularities": fireworks_config.timestamp_granularities,
                "preprocessing": fireworks_config.preprocessing,
            },
            "audio_file": {
                "path": str(audio_path),  # Convert Path to string for JSON serialization
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
    name="api.tasks.processing.process_recording",
    max_retries=1,
    default_retry_delay=600,
)
def process_recording_task(
    self,
    recording_id: int,
    user_id: int,
    manual_override: dict | None = None,
) -> dict:
    """
    Полный пайплайн обработки: download → trim → transcribe → topics → upload.

    Template-driven: все параметры берутся из resolved config (user_config < template < manual_override).

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        manual_override: Опциональное переопределение конфигурации (любые поля)

    Returns:
        Результаты полного пайплайна
    """
    try:
        logger.info(f"[Task {self.request.id}] Processing recording {recording_id}, user {user_id}")

        from api.helpers.config_resolution_helper import resolve_full_config
        from api.tasks.upload import upload_recording_to_platform
        from database.config import DatabaseConfig
        from database.manager import DatabaseManager

        manual_override = manual_override or {}

        # Resolve configuration from hierarchy using helper
        db_config = DatabaseConfig.from_env()
        db_manager = DatabaseManager(db_config)

        async def _resolve_config_and_presets():
            async with db_manager.async_session() as session:
                # Resolve config
                full_config, output_config, recording = await resolve_full_config(
                    session, recording_id, user_id, manual_override, include_output_config=True
                )

                # Load presets in the same async context
                preset_ids_list = output_config.get("preset_ids", [])
                presets = []
                if preset_ids_list:
                    from api.repositories.template_repos import OutputPresetRepository
                    preset_repo = OutputPresetRepository(session)
                    for preset_id in preset_ids_list:
                        preset = await preset_repo.find_by_id(preset_id, user_id)
                        if preset:
                            presets.append(preset)

                return full_config, output_config, recording, presets

        import asyncio
        full_config, output_config, recording, presets = asyncio.run(_resolve_config_and_presets())

        # Skip blank records
        if recording.blank_record:
            logger.info(
                f"[Task {self.request.id}] Skipping full_pipeline for recording {recording_id}: marked as blank_record "
                f"(duration={recording.duration}min, size={recording.video_file_size} bytes)"
            )

            # Update status to SKIPPED
            async def _mark_skipped():
                async with db_manager.async_session() as session:
                    from api.repositories.recording_repos import RecordingAsyncRepository
                    recording_repo = RecordingAsyncRepository(session)
                    rec = await recording_repo.get_by_id(recording_id, user_id)
                    if rec:
                        rec.status = ProcessingStatus.SKIPPED
                        rec.failed_reason = "Blank record (too short or too small)"
                        await session.commit()

            asyncio.run(_mark_skipped())

            return {
                "task_id": self.request.id,
                "status": "skipped",
                "reason": "blank_record",
                "recording_id": recording_id,
            }

        logger.info(
            f"[Task {self.request.id}] Resolved config for recording {recording_id}: "
            f"template_id={recording.template_id}, has_manual_override={bool(recording.processing_preferences)}"
        )

        # Extract pipeline parameters from resolved config
        processing = full_config.get("processing", {})
        transcription = full_config.get("transcription", {})

        # Pipeline steps
        download = True  # Always download if not already downloaded
        process = processing.get("enable_processing", True)
        transcribe = transcription.get("enable_transcription", True)
        extract_topics = transcription.get("enable_topics", True)
        generate_subs = transcription.get("enable_subtitles", True)

        # Upload configuration from output_config (not full_config!)
        upload = output_config.get("auto_upload", False)
        preset_ids_list = output_config.get("preset_ids", [])

        # Fallback: check in full_config["upload"] for backward compatibility
        if not upload and "upload" in full_config:
            upload = full_config["upload"].get("auto_upload", False)

        # Platforms (can be in either location)
        platforms = output_config.get("default_platforms", [])
        if not platforms and "upload" in full_config:
            platforms = full_config["upload"].get("default_platforms", [])

        # Processing parameters
        granularity = transcription.get("granularity", "long")

        logger.info(
            f"[Task {self.request.id}] Pipeline steps: "
            f"download={download}, process={process}, transcribe={transcribe}, "
            f"extract_topics={extract_topics}, generate_subs={generate_subs}, "
            f"upload={upload}, preset_ids={preset_ids_list}, platforms={platforms}"
        )

        results = {
            "recording_id": recording_id,
            "steps_completed": [],
            "errors": [],
        }

        total_steps = sum([download, process, transcribe, extract_topics, generate_subs, upload and len(platforms) > 0])
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

                # Call async function directly (bypass Celery task wrapper to avoid .run() issues)
                download_result = asyncio.run(
                    _async_download_recording(self, recording_id, user_id, False, manual_override)
                )

                results["steps_completed"].append("download")
                results["download"] = download_result
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

                # Call async function directly (bypass Celery task wrapper to avoid .run() issues)
                process_result = asyncio.run(
                    _async_process_video(self, recording_id, user_id, manual_override)
                )

                results["steps_completed"].append("process")
                results["process"] = process_result
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

                # Call async function directly (bypass Celery task wrapper to avoid .run() issues)
                transcribe_result = asyncio.run(
                    _async_transcribe_recording(self, recording_id, user_id, manual_override)
                )

                results["steps_completed"].append("transcribe")
                results["transcribe"] = transcribe_result
                current_step += 1
            except Exception as e:
                results["errors"].append(f"Transcription failed: {str(e)}")
                logger.error(f"Transcription step failed: {e}")

        # STEP 4: Extract Topics
        if extract_topics:
            try:
                self.update_state(
                    state='PROCESSING',
                    meta={
                        'progress': int((current_step / total_steps) * 100),
                        'status': 'Extracting topics...',
                        'step': 'extract_topics'
                    }
                )

                # Call async function directly
                topics_result = asyncio.run(
                    _async_extract_topics(self, recording_id, user_id, granularity, None)
                )

                results["steps_completed"].append("extract_topics")
                results["extract_topics"] = topics_result
                current_step += 1
            except Exception as e:
                results["errors"].append(f"Topic extraction failed: {str(e)}")
                logger.error(f"Topic extraction step failed: {e}")

        # STEP 5: Generate Subtitles
        if generate_subs:
            try:
                self.update_state(
                    state='PROCESSING',
                    meta={
                        'progress': int((current_step / total_steps) * 100),
                        'status': 'Generating subtitles...',
                        'step': 'generate_subtitles'
                    }
                )

                # Get subtitle formats from config
                subtitle_formats = transcription.get("subtitle_formats", ["srt", "vtt"])

                # Call async function directly
                subtitles_result = asyncio.run(
                    _async_generate_subtitles(self, recording_id, user_id, subtitle_formats)
                )

                results["steps_completed"].append("generate_subtitles")
                results["generate_subtitles"] = subtitles_result
                current_step += 1
            except Exception as e:
                results["errors"].append(f"Subtitle generation failed: {str(e)}")
                logger.error(f"Subtitle generation step failed: {e}")

        # STEP 6: Upload
        if upload and (platforms or preset_ids_list):
            # Build platform -> preset_id mapping (presets already loaded at the start)
            preset_map = {preset.platform: preset.id for preset in presets}

            # If platforms not specified, use platforms from presets
            if not platforms and presets:
                platforms = [preset.platform for preset in presets]

            # Extract metadata override from full_config
            # metadata_config is NOT flattened, so it's in its own key
            metadata_override = full_config.get("metadata_config", {})
            if metadata_override:
                logger.info(f"Using metadata_config override for uploads: {list(metadata_override.keys())}")

            upload_task_ids = []
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

                    preset_id = preset_map.get(platform)

                    # Launch upload asynchronously without blocking (Celery best practice)
                    upload_task = upload_recording_to_platform.delay(
                        recording_id, user_id, platform, preset_id, None, metadata_override
                    )

                    upload_task_ids.append({
                        "platform": platform,
                        "task_id": upload_task.id,
                        "preset_id": preset_id,
                    })
                    logger.info(f"Upload task for {platform} launched: {upload_task.id}")
                except Exception as e:
                    results["errors"].append(f"Failed to launch upload to {platform}: {str(e)}")
                    logger.error(f"Failed to launch upload to {platform}: {e}")

            if upload_task_ids:
                results["steps_completed"].append("upload")
                results["upload"] = {
                    "status": "launched",
                    "tasks": upload_task_ids,
                }
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

        result = asyncio.run(
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

        result = asyncio.run(
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


@celery_app.task(
    bind=True,
    base=ProcessingTask,
    name="api.tasks.processing.batch_transcribe_recording",
    max_retries=3,
    default_retry_delay=300,
)
def batch_transcribe_recording_task(
    self,
    recording_id: int,
    user_id: int,
    batch_id: str,
    poll_interval: float = 10.0,
    max_wait_time: float = 3600.0,
) -> dict:
    """
    Polling для Fireworks Batch API transcription.

    Этот task создается после submit_batch_transcription() и ждет завершения batch job.
    Использует polling для проверки статуса каждые poll_interval секунд.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        batch_id: ID batch job от Fireworks
        poll_interval: Интервал проверки статуса (секунды)
        max_wait_time: Максимальное время ожидания (секунды)

    Returns:
        Результат транскрибации
    """
    try:
        logger.info(
            f"[Task {self.request.id}] Batch transcription polling | recording={recording_id} | user={user_id} | batch_id={batch_id}"
        )

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': 'Waiting for batch transcription...', 'step': 'batch_transcribe'}
        )

        result = asyncio.run(
            _async_poll_batch_transcription(
                self,
                recording_id,
                user_id,
                batch_id,
                poll_interval,
                max_wait_time,
            )
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "batch_id": batch_id,
            "result": result,
        }

    except TimeoutError as exc:
        logger.error(
            f"[Task {self.request.id}] Batch transcription timeout | batch_id={batch_id} | max_wait={max_wait_time}s"
        )
        raise self.retry(countdown=600, exc=exc)

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded")
        raise self.retry(countdown=900, exc=SoftTimeLimitExceeded())

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error in batch transcription: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_poll_batch_transcription(
    task_self,
    recording_id: int,
    user_id: int,
    batch_id: str,
    poll_interval: float,
    max_wait_time: float,
) -> dict:
    """Async функция для polling batch transcription."""
    import time

    from fireworks_module import FireworksConfig, FireworksTranscriptionService
    from transcription_module.manager import TranscriptionManager

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)
    session = await db_manager.async_session()

    try:
        recording_repo = RecordingAsyncRepository(session)
        recording_db = await recording_repo.find_by_id(recording_id, user_id)

        if not recording_db:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        recording = MeetingRecording.from_db_model(recording_db)

        # Инициализируем Fireworks service
        fireworks_config = FireworksConfig.from_file("config/fireworks_creds.json")
        fireworks_service = FireworksTranscriptionService(fireworks_config)

        # Polling loop
        start_time = time.time()
        attempt = 0

        while True:
            attempt += 1
            elapsed = time.time() - start_time

            if elapsed > max_wait_time:
                raise TimeoutError(
                    f"Batch transcription {batch_id} не завершился за {max_wait_time}s (попыток: {attempt})"
                )

            # Проверяем статус
            status_response = await fireworks_service.check_batch_status(batch_id)
            status = status_response.get("status", "unknown")

            # Обновляем progress (примерно)
            progress = min(20 + int((elapsed / max_wait_time) * 60), 80)
            task_self.update_state(
                state='PROCESSING',
                meta={
                    'progress': progress,
                    'status': f'Batch transcribing... ({status}, {elapsed:.0f}s)',
                    'step': 'batch_transcribe',
                    'batch_id': batch_id,
                    'attempt': attempt,
                }
            )

            if status == "completed":
                logger.info(
                    f"[Batch Transcription] Completed ✅ | batch_id={batch_id} | elapsed={elapsed:.1f}s | attempts={attempt}"
                )

                task_self.update_state(
                    state='PROCESSING',
                    meta={'progress': 85, 'status': 'Parsing batch result...', 'step': 'batch_transcribe'}
                )

                # Получаем результат
                transcription_result = await fireworks_service.get_batch_result(batch_id)

                # Сохраняем транскрипцию (как обычно)
                transcription_manager = TranscriptionManager()

                task_self.update_state(
                    state='PROCESSING',
                    meta={'progress': 90, 'status': 'Saving transcription...', 'step': 'batch_transcribe'}
                )

                # Сохраняем master.json
                words = transcription_result.get("words", [])
                segments = transcription_result.get("segments", [])
                language = transcription_result.get("language", "ru")

                master_data = {
                    "text": transcription_result.get("text", ""),
                    "segments": segments,
                    "words": words,
                    "language": language,
                }

                transcription_manager.save_master(
                    recording_id=recording_id,
                    master_data=master_data,
                    user_id=user_id,
                )

                # Обновляем запись в БД
                recording.transcription_path = transcription_manager.get_dir(recording_id, user_id=user_id)
                recording.mark_stage_completed(
                    ProcessingStageType.TRANSCRIBE,
                    meta={
                        "batch_id": batch_id,
                        "language": language,
                        "words_count": len(words),
                        "segments_count": len(segments),
                        "elapsed_seconds": elapsed,
                    },
                )

                # Обновляем агрегированный статус
                from api.helpers.status_manager import update_aggregate_status
                update_aggregate_status(recording)

                await recording_repo.update(recording)
                await session.commit()

                return {
                    "success": True,
                    "batch_id": batch_id,
                    "language": language,
                    "elapsed_seconds": elapsed,
                    "attempts": attempt,
                }

            logger.debug(
                f"[Batch Transcription] Polling | batch_id={batch_id} | status={status} | attempt={attempt} | elapsed={elapsed:.1f}s"
            )

            await asyncio.sleep(poll_interval)

    finally:
        await session.close()
