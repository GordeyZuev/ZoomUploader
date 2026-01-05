"""Celery tasks для загрузки видео с multi-tenancy support."""

import asyncio

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from api.celery_app import celery_app
from api.core.context import ServiceContext
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from logger import get_logger
from video_upload_module.factory import UploaderFactory

logger = get_logger()


class UploadTask(Task):
    """Базовый класс для задач загрузки с multi-tenancy."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Обработка ошибки задачи."""
        user_id = kwargs.get("user_id", "unknown")
        logger.error(f"Upload task {task_id} for user {user_id} failed: {exc}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Обработка повторной попытки."""
        user_id = kwargs.get("user_id", "unknown")
        logger.warning(f"Upload task {task_id} for user {user_id} retrying: {exc}")

    def on_success(self, retval, task_id, args, kwargs):
        """Обработка успешного завершения."""
        user_id = kwargs.get("user_id", "unknown")
        logger.info(f"Upload task {task_id} for user {user_id} completed successfully")


@celery_app.task(
    bind=True,
    base=UploadTask,
    name="api.tasks.upload.upload_recording_to_platform",
    max_retries=3,
    default_retry_delay=600,  # 10 минут между попытками
)
def upload_recording_to_platform(
    self,
    recording_id: int,
    user_id: int,
    platform: str,
    preset_id: int | None = None,
    credential_id: int | None = None,
) -> dict:
    """
    Загрузка одной записи на платформу с user credentials.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        platform: Платформа (youtube, vk)
        preset_id: ID output preset (опционально)
        credential_id: ID credential (опционально)

    Returns:
        Словарь с результатами загрузки
    """
    try:
        logger.info(
            f"[Task {self.request.id}] Uploading recording {recording_id} "
            f"for user {user_id} to {platform}"
        )

        # Создаем async event loop
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Выполняем async загрузку
        result = loop.run_until_complete(
            _async_upload_recording(
                recording_id=recording_id,
                user_id=user_id,
                platform=platform,
                preset_id=preset_id,
                credential_id=credential_id,
            )
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "recording_id": recording_id,
            "platform": platform,
            "result": result,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded")
        raise self.retry(countdown=900, exc=SoftTimeLimitExceeded())

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error uploading: {exc}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_upload_recording(
    recording_id: int,
    user_id: int,
    platform: str,
    preset_id: int | None = None,
    credential_id: int | None = None,
) -> dict:
    """
    Async функция для загрузки записи.

    Args:
        recording_id: ID записи
        user_id: ID пользователя
        platform: Платформа
        preset_id: ID output preset
        credential_id: ID credential

    Returns:
        Результаты загрузки
    """
    from pathlib import Path

    from api.repositories.recording_repos import RecordingAsyncRepository

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        ctx = ServiceContext.create(session=session, user_id=user_id)
        recording_repo = RecordingAsyncRepository(session)

        # Получить запись из БД
        recording = await recording_repo.get_by_id(recording_id, user_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found for user {user_id}")

        if not recording.processed_video_path:
            raise ValueError(f"Recording {recording_id} has no processed video")

        video_path = recording.processed_video_path
        if not Path(video_path).exists():
            raise ValueError(f"Video file not found: {video_path}")

        # Создаем uploader
        if preset_id:
            uploader = await UploaderFactory.create_uploader_by_preset_id(
                session=ctx.session,
                user_id=user_id,
                preset_id=preset_id,
            )
        elif credential_id:
            uploader = await UploaderFactory.create_uploader(
                session=ctx.session,
                user_id=user_id,
                platform=platform,
                credential_id=credential_id,
            )
        else:
            uploader = await UploaderFactory.create_uploader(
                session=ctx.session,
                user_id=user_id,
                platform=platform,
            )

        # Аутентификация
        auth_success = await uploader.authenticate()
        if not auth_success:
            raise Exception(f"Failed to authenticate with {platform}")

        # Получить параметры из recording
        title = recording.display_name
        description = f"Uploaded on {recording.start_time.strftime('%Y-%m-%d')}"

        if recording.main_topics:
            topics_str = ", ".join(recording.main_topics[:5])
            description += f"\n\nТемы: {topics_str}"

        # Загрузка
        upload_result = await uploader.upload_video(
            video_path=video_path,
            title=title,
            description=description,
        )

        if not upload_result or not upload_result.success:
            raise Exception(
                f"Upload failed: {upload_result.error if upload_result else 'Unknown error'}"
            )

        # Сохранить результаты в БД
        target_type_map = {
            "youtube": "YOUTUBE",
            "vk": "VK",
        }

        target_type = target_type_map.get(platform.lower(), platform.upper())

        await recording_repo.save_upload_result(
            recording=recording,
            target_type=target_type,
            preset_id=preset_id,
            video_id=upload_result.video_id,
            video_url=upload_result.video_url,
            target_meta={"platform": platform, "uploaded_by_task": True},
        )

        await session.commit()

        return {
            "success": True,
            "video_id": upload_result.video_id,
            "video_url": upload_result.video_url,
        }


@celery_app.task(
    bind=True,
    base=UploadTask,
    name="api.tasks.upload.batch_upload_recordings",
    max_retries=1,
)
def batch_upload_recordings(
    self,
    recording_ids: list[int],
    user_id: int,
    platforms: list[str],
    preset_ids: dict[str, int] | None = None,
) -> dict:
    """
    Пакетная загрузка записей на платформы.

    Args:
        recording_ids: Список ID записей
        user_id: ID пользователя
        platforms: Список платформ (youtube, vk)
        preset_ids: Словарь {platform: preset_id} (опционально)

    Returns:
        Словарь с результатами загрузки
    """
    try:
        logger.info(
            f"[Task {self.request.id}] Batch uploading {len(recording_ids)} recordings "
            f"for user {user_id} to {platforms}"
        )

        results = []
        for recording_id in recording_ids:
            for platform in platforms:
                # Создаем subtask для каждой комбинации recording+platform
                preset_id = preset_ids.get(platform) if preset_ids else None

                subtask_result = upload_recording_to_platform.delay(
                    recording_id=recording_id,
                    user_id=user_id,
                    platform=platform,
                    preset_id=preset_id,
                )

                results.append(
                    {
                        "recording_id": recording_id,
                        "platform": platform,
                        "task_id": subtask_result.id,
                        "status": "queued",
                    }
                )

        return {
            "task_id": self.request.id,
            "status": "dispatched",
            "subtasks": results,
        }

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error in batch upload: {exc}", exc_info=True)
        raise
