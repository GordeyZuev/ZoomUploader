"""Dependency Injection для FastAPI."""

from collections.abc import AsyncGenerator
from functools import lru_cache

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import get_settings
from config.settings import settings

api_settings = get_settings()


@lru_cache
def get_async_engine():
    """Получение async engine для SQLAlchemy."""
    return create_async_engine(settings.database.url, echo=False)


def get_async_session_maker():
    """Получение session maker для async sessions."""
    engine = get_async_engine()
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Получение async database session."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


_redis_client = None


async def get_redis() -> redis.Redis:
    """Получение async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            api_settings.celery_broker_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client
