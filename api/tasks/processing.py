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
from models import MeetingRecording, ProcessingStatus
from transcription_module.factory import TranscriptionServiceFactory
from video_download_module.downloader import ZoomDownloader
from video_processing_module.video_processor import VideoProcessor

logger = get_logger()


class ProcessingTask(Task):
    """Базовый класс для задач обработки с multi-tenancy."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Обработка ошибки задачи."""
        user_id = kwargs.get("user_id", "unknown")
        recording_id = kwargs.get("recording_id", "unknown")
        logger.error(f"Task {task_id} for user {user_id}, recording {recording_id} failed: {exc}")

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
        logger.error(f"[Task {self.request.id}] Error downloading: {exc}", exc_info=True)
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
        logger.error(f"[Task {self.request.id}] Error processing: {exc}", exc_info=True)
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
                meta={'progress': 90, 'status': 'Updating database...', 'step': 'process'}
            )

            recording.processed_video_path = processed_path
            recording.status = ProcessingStatus.PROCESSED
            await recording_repo.update(recording)
            await session.commit()

            return {
                "success": True,
                "processed_video_path": processed_path,
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
    granularity: str = "long",
) -> dict:
    """
    Транскрибация записи с user credentials.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        granularity: Режим извлечения тем

    Returns:
        Результаты транскрибации
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
            _async_transcribe_recording(self, recording_id, user_id, granularity)
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
        logger.error(f"[Task {self.request.id}] Error transcribing: {exc}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_transcribe_recording(task_self, recording_id: int, user_id: int, granularity: str) -> dict:
    """Async функция для транскрибации."""
    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        recording_repo = RecordingAsyncRepository(session)

        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        if not recording.processed_video_path and not recording.local_video_path:
            raise ValueError("No video file available for transcription")

        audio_path = recording.processed_video_path or recording.local_video_path

        if not Path(audio_path).exists():
            raise ValueError(f"Video file not found: {audio_path}")

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 20, 'status': 'Loading transcription service...', 'step': 'transcribe'}
        )

        # Создаем TranscriptionService
        transcription_service = await TranscriptionServiceFactory.create_for_user(
            session=session,
            user_id=user_id,
        )

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 30, 'status': 'Transcribing audio...', 'step': 'transcribe'}
        )

        # Транскрибация
        result = await transcription_service.process_audio(
            audio_path=audio_path,
            recording_id=recording_id,
            recording_topic=recording.display_name,
            recording_start_time=recording.start_time.isoformat(),
            granularity=granularity,
        )

        task_self.update_state(
            state='PROCESSING',
            meta={'progress': 90, 'status': 'Saving results...', 'step': 'transcribe'}
        )

        # Сохранить результаты в БД
        await recording_repo.save_transcription_result(
            recording=recording,
            transcription_dir=result["transcription_dir"],
            transcription_info=result.get("fireworks_raw", {}),
            topic_timestamps=result["topic_timestamps"],
            main_topics=result["main_topics"],
        )

        await session.commit()

        return {
            "success": True,
            "transcription_dir": result["transcription_dir"],
            "topics_count": len(result["topic_timestamps"]),
            "main_topics": result["main_topics"],
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
                    args=[recording_id, user_id, granularity]
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
        logger.error(f"[Task {self.request.id}] Full pipeline failed: {exc}", exc_info=True)
        raise
