"""Celery tasks for syncing sources with multi-tenancy support."""

import asyncio

from api.celery_app import celery_app
from api.repositories.template_repos import InputSourceRepository
from api.tasks.base import SyncTask
from database.manager import DatabaseManager
from logger import get_logger

logger = get_logger()


@celery_app.task(
    bind=True,
    base=SyncTask,
    name="api.tasks.sync.sync_single_source",
    max_retries=3,
    default_retry_delay=300,
)
def sync_single_source_task(
    self,
    source_id: int,
    user_id: int,
    from_date: str = "2024-01-01",
    to_date: str | None = None,
) -> dict:
    """
    Syncing one source (Celery task).

    Args:
        source_id: ID of source
        user_id: ID of user
        from_date: Start date in format YYYY-MM-DD
        to_date: End date in format YYYY-MM-DD (optional)

    Returns:
        Result of syncing
    """
    try:
        logger.info(f"[Task {self.request.id}] Syncing source {source_id} for user {user_id}")

        self.update_progress(user_id, 10, f"Syncing source {source_id}...", step="sync")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            # Python 3.13+: get_event_loop() raises RuntimeError if no loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_sync_single_source(self, source_id, user_id, from_date, to_date))
        return self.build_result(user_id=user_id, **result)

    except Exception as e:
        logger.error(f"Sync task failed for source {source_id}: {e}", exc_info=True)
        raise


@celery_app.task(
    bind=True,
    base=SyncTask,
    name="api.tasks.sync.batch_sync_sources",
    max_retries=3,
    default_retry_delay=300,
)
def bulk_sync_sources_task(
    self,
    source_ids: list[int],
    user_id: int,
    from_date: str = "2024-01-01",
    to_date: str | None = None,
) -> dict:
    """
    Batch syncing multiple sources (Celery task).

    Args:
        source_ids: List of source IDs
        user_id: ID of user
        from_date: Start date in format YYYY-MM-DD
        to_date: End date in format YYYY-MM-DD (optional)

    Returns:
        Results of syncing all sources
    """
    try:
        logger.info(f"[Task {self.request.id}] Batch syncing {len(source_ids)} sources for user {user_id}")

        self.update_progress(
            user_id,
            5,
            f"Starting batch sync of {len(source_ids)} sources...",
            step="batch_sync",
        )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            # Python 3.13+: get_event_loop() raises RuntimeError if no loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_async_batch_sync_sources(self, source_ids, user_id, from_date, to_date))
        return self.build_result(user_id=user_id, **result)

    except Exception as e:
        logger.error(f"Batch sync task failed for sources {source_ids}: {e}", exc_info=True)
        raise


async def _async_sync_single_source(
    task,
    source_id: int,
    user_id: int,
    from_date: str,
    to_date: str | None,
) -> dict:
    """Async wrapper for syncing one source."""
    from database.config import DatabaseConfig

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        task.update_progress(user_id, 20, f"Loading source {source_id}...", step="sync")

        # Import here to avoid circular imports
        from api.routers.input_sources import _sync_single_source

        result = await _sync_single_source(source_id, from_date, to_date, session, user_id)

        if result["status"] == "success":
            await session.commit()

            task.update_progress(user_id, 90, "Sync completed", step="sync")

            # Get source for additional information
            repo = InputSourceRepository(session)
            source = await repo.find_by_id(source_id, user_id)

            return {
                "status": "success",
                "source_id": source_id,
                "source_name": source.name if source else None,
                "source_type": source.source_type.value if source else "UNKNOWN",
                "recordings_found": result.get("recordings_found", 0),
                "recordings_saved": result.get("recordings_saved", 0),
                "recordings_updated": result.get("recordings_updated", 0),
            }
        return {
            "status": "error",
            "source_id": source_id,
            "error": result.get("error", "Unknown error"),
        }


async def _async_batch_sync_sources(
    task,
    source_ids: list[int],
    user_id: int,
    from_date: str,
    to_date: str | None,
) -> dict:
    """Async wrapper for batch syncing sources."""
    from database.config import DatabaseConfig

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)
    results = []
    successful = 0
    failed = 0

    async with db_manager.async_session() as session:
        repo = InputSourceRepository(session)

        for idx, source_id in enumerate(source_ids):
            progress = 10 + int((idx / len(source_ids)) * 80)
            task.update_progress(
                user_id,
                progress,
                f"Syncing source {idx + 1}/{len(source_ids)}...",
                step="batch_sync",
                current_source=source_id,
            )

            # Get source for name
            source = await repo.find_by_id(source_id, user_id)
            source_name = source.name if source else None

            try:
                # Import here to avoid circular imports
                from api.routers.input_sources import _sync_single_source

                result = await _sync_single_source(source_id, from_date, to_date, session, user_id)

                if result["status"] == "success":
                    successful += 1
                    results.append(
                        {
                            "source_id": source_id,
                            "source_name": source_name,
                            "status": "success",
                            "recordings_found": result.get("recordings_found"),
                            "recordings_saved": result.get("recordings_saved"),
                            "recordings_updated": result.get("recordings_updated"),
                        }
                    )
                else:
                    failed += 1
                    results.append(
                        {
                            "source_id": source_id,
                            "source_name": source_name,
                            "status": "error",
                            "error": result.get("error", "Unknown error"),
                        }
                    )

            except Exception as e:
                logger.error(f"Unexpected error during sync of source {source_id}: {e}", exc_info=True)
                failed += 1
                results.append(
                    {
                        "source_id": source_id,
                        "source_name": source_name,
                        "status": "error",
                        "error": str(e),
                    }
                )

        await session.commit()

        return {
            "status": "success",
            "message": f"Batch sync completed: {successful} successful, {failed} failed",
            "total_sources": len(source_ids),
            "successful": successful,
            "failed": failed,
            "results": results,
        }
