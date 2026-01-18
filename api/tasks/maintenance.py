"""Celery tasks для обслуживания системы (maintenance)."""

from api.celery_app import celery_app
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from logger import get_logger

logger = get_logger()


@celery_app.task(name="maintenance.cleanup_expired_tokens")
def cleanup_expired_tokens_task():
    """
    Periodic task for cleaning expired refresh tokens.

    Runs daily (configured in Celery Beat).
    """
    try:
        import asyncio

        from api.repositories.auth_repos import RefreshTokenRepository

        logger.info("Starting cleanup of expired refresh tokens...")

        # Start async cleanup
        async def cleanup():
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)

            async with db_manager.async_session() as session:
                token_repo = RefreshTokenRepository(session)
                return await token_repo.delete_expired()

        # Execute async function
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        deleted_count = loop.run_until_complete(cleanup())

        logger.info(f"Cleanup completed: {deleted_count} expired tokens deleted")

        return {
            "status": "success",
            "deleted_tokens": deleted_count,
            "message": f"Cleaned up {deleted_count} expired refresh tokens",
        }

    except Exception as e:
        logger.error(f"Failed to cleanup expired tokens: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
