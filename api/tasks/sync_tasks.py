"""Celery tasks для синхронизации источников с multi-tenancy support."""

import asyncio

from celery import Task

from api.celery_app import celery_app
from api.repositories.template_repos import InputSourceRepository
from database.manager import DatabaseManager
from logger import get_logger

logger = get_logger()


class SyncTask(Task):
    """Базовый класс для задач синхронизации с multi-tenancy."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Обработка ошибки задачи."""
        user_id = kwargs.get("user_id", "unknown")
        source_ids = kwargs.get("source_ids", kwargs.get("source_id", "unknown"))
        logger.error(f"Sync task {task_id} for user {user_id}, sources {source_ids} failed: {exc!r}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Обработка повторной попытки."""
        user_id = kwargs.get("user_id", "unknown")
        logger.warning(f"Sync task {task_id} for user {user_id} retrying: {exc}")

    def on_success(self, retval, task_id, args, kwargs):
        """Обработка успешного завершения."""
        user_id = kwargs.get("user_id", "unknown")
        logger.info(f"Sync task {task_id} for user {user_id} completed successfully")


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
    Синхронизация одного источника (Celery task).

    Args:
        source_id: ID источника
        user_id: ID пользователя
        from_date: Дата начала в формате YYYY-MM-DD
        to_date: Дата окончания в формате YYYY-MM-DD (опционально)

    Returns:
        Результат синхронизации
    """
    try:
        logger.info(f"[Task {self.request.id}] Syncing source {source_id} for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 10, 'status': f'Syncing source {source_id}...', 'step': 'sync'}
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

        result = loop.run_until_complete(
            _async_sync_single_source(self, source_id, user_id, from_date, to_date)
        )

        return result

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
    Батчевая синхронизация нескольких источников (Celery task).

    Args:
        source_ids: Список ID источников
        user_id: ID пользователя
        from_date: Дата начала в формате YYYY-MM-DD
        to_date: Дата окончания в формате YYYY-MM-DD (опционально)

    Returns:
        Результаты синхронизации всех источников
    """
    try:
        logger.info(f"[Task {self.request.id}] Batch syncing {len(source_ids)} sources for user {user_id}")

        self.update_state(
            state='PROCESSING',
            meta={'progress': 5, 'status': f'Starting batch sync of {len(source_ids)} sources...', 'step': 'batch_sync'}
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

        result = loop.run_until_complete(
            _async_batch_sync_sources(self, source_ids, user_id, from_date, to_date)
        )

        return result

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
    """Async обертка для синхронизации одного источника."""
    from database.config import DatabaseConfig

    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        task.update_state(
            state='PROCESSING',
            meta={'progress': 20, 'status': f'Loading source {source_id}...', 'step': 'sync'}
        )

        # Import здесь чтобы избежать circular imports
        from api.routers.input_sources import _sync_single_source

        result = await _sync_single_source(source_id, from_date, to_date, session, user_id)

        if result["status"] == "success":
            await session.commit()

            task.update_state(
                state='PROCESSING',
                meta={'progress': 90, 'status': 'Sync completed', 'step': 'sync'}
            )

            # Получаем source для дополнительной информации
            repo = InputSourceRepository(session)
            source = await repo.find_by_id(source_id, user_id)

            return {
                "status": "success",
                "source_id": source_id,
                "source_name": source.name if source else None,
                "source_type": source.source_type if source else "UNKNOWN",
                "recordings_found": result.get("recordings_found", 0),
                "recordings_saved": result.get("recordings_saved", 0),
                "recordings_updated": result.get("recordings_updated", 0),
            }
        else:
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
    """Async обертка для батчевой синхронизации источников."""
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
            task.update_state(
                state='PROCESSING',
                meta={
                    'progress': progress,
                    'status': f'Syncing source {idx + 1}/{len(source_ids)}...',
                    'step': 'batch_sync',
                    'current_source': source_id,
                }
            )

            # Получаем source для имени
            source = await repo.find_by_id(source_id, user_id)
            source_name = source.name if source else None

            try:
                # Import здесь чтобы избежать circular imports
                from api.routers.input_sources import _sync_single_source

                result = await _sync_single_source(source_id, from_date, to_date, session, user_id)

                if result["status"] == "success":
                    successful += 1
                    results.append({
                        "source_id": source_id,
                        "source_name": source_name,
                        "status": "success",
                        "recordings_found": result.get("recordings_found"),
                        "recordings_saved": result.get("recordings_saved"),
                        "recordings_updated": result.get("recordings_updated"),
                    })
                else:
                    failed += 1
                    results.append({
                        "source_id": source_id,
                        "source_name": source_name,
                        "status": "error",
                        "error": result.get("error", "Unknown error"),
                    })

            except Exception as e:
                logger.error(f"Unexpected error during sync of source {source_id}: {e}", exc_info=True)
                failed += 1
                results.append({
                    "source_id": source_id,
                    "source_name": source_name,
                    "status": "error",
                    "error": str(e),
                })

        await session.commit()

        return {
            "status": "success",
            "message": f"Batch sync completed: {successful} successful, {failed} failed",
            "total_sources": len(source_ids),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

