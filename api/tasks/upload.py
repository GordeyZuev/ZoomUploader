"""Celery tasks для загрузки видео с multi-tenancy support."""

import asyncio

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from api.celery_app import celery_app
from api.core.context import ServiceContext
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from logger import get_logger
from video_upload_module.uploader_factory import create_uploader_from_db

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

        # Выполняем async загрузку
        result = asyncio.run(
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
        logger.error(f"[Task {self.request.id}] Error uploading: {type(exc).__name__}: {str(exc)}", exc_info=True)
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

    from api.helpers.template_renderer import TemplateRenderer
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

        # DEBUG: Check what data is loaded from DB
        logger.info(f"[Upload] Recording {recording_id} loaded from DB")
        logger.info(f"[Upload] Recording has main_topics: {hasattr(recording, 'main_topics')} = {getattr(recording, 'main_topics', None)}")
        logger.info(f"[Upload] Recording has topic_timestamps: {hasattr(recording, 'topic_timestamps')} = {type(getattr(recording, 'topic_timestamps', None))}")
        if hasattr(recording, 'topic_timestamps') and recording.topic_timestamps:
            logger.info(f"[Upload] topic_timestamps is list: {isinstance(recording.topic_timestamps, list)}, length: {len(recording.topic_timestamps) if isinstance(recording.topic_timestamps, list) else 'N/A'}")

        if not recording.processed_video_path:
            raise ValueError(f"Recording {recording_id} has no processed video")

        video_path = recording.processed_video_path
        if not Path(video_path).exists():
            raise ValueError(f"Video file not found: {video_path}")

        # Создать или получить output_target и пометить как UPLOADING
        target_type_map = {
            "youtube": "YOUTUBE",
            "vk": "VK",
        }
        target_type = target_type_map.get(platform.lower(), platform.upper())

        output_target = await recording_repo.get_or_create_output_target(
            recording=recording,
            target_type=target_type,
            preset_id=preset_id,
        )

        await recording_repo.mark_output_uploading(output_target)

        # Initialize preset metadata
        preset_metadata = {}
        preset = None

        # Создаем uploader с новым factory
        if preset_id:
            # Get preset to extract platform and credential_id
            from api.repositories.template_repos import OutputPresetRepository

            preset_repo = OutputPresetRepository(ctx.session)
            preset = await preset_repo.find_by_id(preset_id, user_id)

            if not preset:
                raise ValueError(f"Output preset {preset_id} not found for user {user_id}")

            if not preset.credential_id:
                raise ValueError(f"Output preset {preset_id} has no credential configured")

            # Extract preset metadata
            preset_metadata = preset.preset_metadata or {}
            logger.info(f"Using preset {preset.name} with metadata: {list(preset_metadata.keys())}")

            # Map platform names
            platform_map = {"YOUTUBE": "youtube", "VK": "vk_video", "VK_VIDEO": "vk_video"}
            mapped_platform = platform_map.get(preset.platform.upper(), preset.platform.lower())

            uploader = await create_uploader_from_db(
                platform=mapped_platform,
                credential_id=preset.credential_id,
                session=ctx.session,
            )
        elif credential_id:
            # Use specified credential
            uploader = await create_uploader_from_db(
                platform=platform,
                credential_id=credential_id,
                session=ctx.session,
            )
        else:
            # No credential specified - need to find default
            from api.repositories.auth_repos import UserCredentialRepository

            cred_repo = UserCredentialRepository(ctx.session)
            credentials = await cred_repo.list_by_platform(user_id, platform)

            if not credentials:
                raise ValueError(f"No credentials found for platform {platform}")

            # Use first available credential
            uploader = await create_uploader_from_db(
                platform=platform,
                credential_id=credentials[0].id,
                session=ctx.session,
            )

        # Prepare template context from recording with topics_display config
        topics_display = preset_metadata.get("topics_display") if preset_metadata else None
        template_context = TemplateRenderer.prepare_recording_context(recording, topics_display)

        # DEBUG: Log context and preset metadata
        logger.info(f"[Upload {platform}] Preset metadata keys: {list(preset_metadata.keys()) if preset_metadata else 'None'}")
        logger.info(f"[Upload {platform}] Template context keys: {list(template_context.keys())}")
        logger.info(f"[Upload {platform}] Has topic_timestamps: {hasattr(recording, 'topic_timestamps') and recording.topic_timestamps is not None}")
        if hasattr(recording, 'topic_timestamps') and recording.topic_timestamps:
            logger.info(f"[Upload {platform}] topic_timestamps count: {len(recording.topic_timestamps)}")
        logger.info(f"[Upload {platform}] Has main_topics: {hasattr(recording, 'main_topics') and recording.main_topics is not None}")
        if hasattr(recording, 'main_topics') and recording.main_topics:
            logger.info(f"[Upload {platform}] main_topics: {recording.main_topics}")

        # Аутентификация
        auth_success = await uploader.authenticate()
        if not auth_success:
            raise Exception(f"Failed to authenticate with {platform}")

        # Prepare title and description from templates or defaults
        title_template = preset_metadata.get("title_template", "{display_name}")
        description_template = preset_metadata.get(
            "description_template",
            "Uploaded on {start_time}"
        )

        logger.info(f"[Upload {platform}] title_template: {title_template[:100]}...")
        logger.info(f"[Upload {platform}] description_template: {description_template[:200]}...")

        title = TemplateRenderer.render(title_template, template_context, topics_display)
        description = TemplateRenderer.render(description_template, template_context, topics_display)

        logger.info(f"[Upload {platform}] Rendered title: {title[:100] if title else 'EMPTY'}")
        logger.info(f"[Upload {platform}] Rendered description length: {len(description)} chars")
        logger.info(f"[Upload {platform}] Rendered description preview: {description[:200] if description else 'EMPTY'}")

        # Fallback if templates produced empty strings
        if not title:
            logger.warning(f"[Upload {platform}] Title is empty, using fallback")
            title = recording.display_name or "Recording"
        if not description:
            logger.warning(f"[Upload {platform}] Description is empty, using fallback")
            description = f"Uploaded on {recording.start_time.strftime('%Y-%m-%d')}"
            if recording.main_topics:
                # Use topics_display for fallback if configured
                if topics_display and topics_display.get("enabled", True):
                    topics_str = TemplateRenderer._format_topics_list(recording.main_topics, topics_display)
                else:
                    topics_str = ", ".join(recording.main_topics[:5])
                description += f"\n\n{topics_str}"

        logger.info(f"[Upload {platform}] Final title: {title[:50]}...")
        logger.info(f"[Upload {platform}] Final description length: {len(description)}")

        # Prepare upload parameters from preset_metadata
        upload_params = {
            "video_path": video_path,
            "title": title,
            "description": description,
        }

        # Add platform-specific parameters from preset
        if platform.lower() in ["youtube"]:
            # YouTube-specific parameters
            if "tags" in preset_metadata:
                upload_params["tags"] = preset_metadata["tags"]

            if "category_id" in preset_metadata:
                upload_params["category_id"] = preset_metadata["category_id"]

            if "privacy" in preset_metadata:
                upload_params["privacy_status"] = preset_metadata["privacy"]

            if "playlist_id" in preset_metadata:
                upload_params["playlist_id"] = preset_metadata["playlist_id"]

            if "publish_at" in preset_metadata:
                upload_params["publish_at"] = preset_metadata["publish_at"]

            if "thumbnail_path" in preset_metadata and preset_metadata["thumbnail_path"]:
                thumbnail_path = Path(preset_metadata["thumbnail_path"])
                if thumbnail_path.exists():
                    upload_params["thumbnail_path"] = str(thumbnail_path)
                else:
                    logger.warning(f"Thumbnail not found: {thumbnail_path}")

            # Additional YouTube params
            for key in ["made_for_kids", "embeddable", "license", "public_stats_viewable"]:
                if key in preset_metadata:
                    upload_params[key] = preset_metadata[key]

        elif platform.lower() in ["vk", "vk_video"]:
            # VK-specific parameters
            if "album_id" in preset_metadata:
                upload_params["album_id"] = str(preset_metadata["album_id"])

            if "thumbnail_path" in preset_metadata and preset_metadata["thumbnail_path"]:
                thumbnail_path = Path(preset_metadata["thumbnail_path"])
                if thumbnail_path.exists():
                    upload_params["thumbnail_path"] = str(thumbnail_path)

            # VK privacy and other settings (including group_id for group uploads)
            for key in ["group_id", "privacy_view", "privacy_comment", "no_comments", "repeat", "wallpost"]:
                if key in preset_metadata:
                    upload_params[key] = preset_metadata[key]

        # Загрузка
        try:
            upload_result = await uploader.upload_video(**upload_params)

            if not upload_result or upload_result.error_message:
                error_message = upload_result.error_message if upload_result else 'Unknown error'
                await recording_repo.mark_output_failed(output_target, f"Upload failed: {error_message}")
                await session.commit()
                raise Exception(f"Upload failed: {error_message}")

            # Сохранить результаты в БД (обновит статус на UPLOADED)
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

        except Exception as e:
            # Mark as failed if not already marked
            if output_target.status != "FAILED":
                await recording_repo.mark_output_failed(output_target, str(e))
                await session.commit()
            raise


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
