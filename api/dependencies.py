"""Dependency Injection для FastAPI."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings


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
