"""Celery tasks для работы с templates."""

import asyncio
import logging

from api.celery_app import celery_app
from api.repositories.template_repos import RecordingTemplateRepository
from api.tasks.base import TemplateTask
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from models.recording import ProcessingStatus

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    base=TemplateTask,
    name="api.tasks.template.rematch_recordings",
    max_retries=2,
    default_retry_delay=60,
)
def rematch_recordings_task(
    self,
    template_id: int,
    user_id: int,
    only_unmapped: bool = True,
) -> dict:
    """
    Re-match recordings after creation/update of template.

    Checks all SKIPPED recordings and updates those that matched to template.
    Updates is_mapped=True, template_id and status=INITIALIZED.

    Args:
        template_id: ID of template for matching
        user_id: ID of user
        only_unmapped: Check only unmapped (SKIPPED) recordings (default: True)

    Returns:
        Dictionary with results:
        - success: bool
        - checked: number of checked recordings
        - matched: number of matched recordings
        - updated: number of updated recordings
        - recordings: list of IDs of updated recordings
    """
    try:
        logger.info(
            f"[Task {self.request.id}] Starting re-match for template {template_id}, "
            f"user {user_id}, only_unmapped={only_unmapped}"
        )

        self.update_progress(user_id, 10, "Loading template...", step="rematch")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            # Python 3.13+: get_event_loop() raises RuntimeError if no loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_rematch_recordings(self, template_id, user_id, only_unmapped))

        logger.info(
            f"[Task {self.request.id}] Re-match completed: "
            f"checked={result['checked']}, matched={result['matched']}, updated={result['updated']}"
        )

        return self.build_result(
            user_id=user_id,
            status="completed",
            result=result,
        )

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error in re-match: {exc!r}", exc_info=True)
        raise self.retry(exc=exc)


async def _async_rematch_recordings(task_self, template_id: int, user_id: int, only_unmapped: bool) -> dict:
    """
    Async функция для re-match recordings.

    Args:
        task_self: Celery task instance
        template_id: ID template
        user_id: ID пользователя
        only_unmapped: Только unmapped recordings

    Returns:
        Dict с результатами
    """
    from sqlalchemy import select

    from database.models import RecordingModel

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        template_repo = RecordingTemplateRepository(session)

        task_self.update_progress(user_id, 20, "Loading template...", step="rematch")

        # Get template
        template = await template_repo.find_by_id(template_id, user_id)
        if not template:
            raise ValueError(f"Template {template_id} not found for user {user_id}")

        if not template.is_active or template.is_draft:
            raise ValueError(
                f"Template {template_id} is not active (is_active={template.is_active}, is_draft={template.is_draft})"
            )

        task_self.update_progress(
            user_id,
            30,
            "Loading recordings...",
            step="rematch",
            template_name=template.name,
        )

        # Get recordings for checking
        query = select(RecordingModel).where(RecordingModel.user_id == user_id)

        if only_unmapped:
            # Only unmapped (SKIPPED) recordings
            query = query.where(
                RecordingModel.is_mapped == False,  # noqa: E712
                RecordingModel.status == ProcessingStatus.SKIPPED,
            )

        query = query.order_by(RecordingModel.created_at.desc())

        result = await session.execute(query)
        recordings = result.scalars().all()

        logger.info(f"[Re-match] Found {len(recordings)} recordings to check for template {template_id}")

        task_self.update_progress(
            user_id,
            40,
            f"Checking {len(recordings)} recordings...",
            step="rematch",
        )

        # Import function for matching
        from api.routers.input_sources import _find_matching_template

        matched_count = 0
        updated_count = 0
        updated_recording_ids = []

        for idx, recording in enumerate(recordings):
            # Check matching
            matched_template = _find_matching_template(
                display_name=recording.display_name,
                source_id=recording.input_source_id or 0,
                templates=[template],
            )

            if matched_template:
                matched_count += 1

                # Update recording only if it is unmapped
                if not recording.is_mapped:
                    old_status = recording.status
                    recording.is_mapped = True
                    recording.template_id = template.id
                    recording.status = ProcessingStatus.INITIALIZED

                    updated_count += 1
                    updated_recording_ids.append(recording.id)

                    logger.info(
                        f"[Re-match] Updated recording {recording.id} '{recording.display_name}': "
                        f"{old_status} → INITIALIZED (template={template.id})"
                    )

            # Update progress
            if idx % 10 == 0:
                progress = 40 + int((idx / len(recordings)) * 50)
                task_self.update_progress(
                    user_id,
                    progress,
                    f"Checked {idx}/{len(recordings)} recordings...",
                    step="rematch",
                    matched_so_far=matched_count,
                )

        # Save changes
        if updated_count > 0:
            task_self.update_progress(user_id, 95, "Saving changes...", step="rematch")

            await session.commit()

            logger.info(f"[Re-match] Committed {updated_count} updates for template {template_id}")

        return {
            "success": True,
            "template_id": template_id,
            "template_name": template.name,
            "checked": len(recordings),
            "matched": matched_count,
            "updated": updated_count,
            "recordings": updated_recording_ids,
        }
