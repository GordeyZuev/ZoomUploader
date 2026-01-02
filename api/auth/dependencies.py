"""Dependencies для аутентификации и авторизации."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.security import JWTHelper
from api.dependencies import get_db_session
from api.repositories.auth_repos import UserQuotaRepository, UserRepository
from api.schemas.auth import UserInDB, UserQuotaCreate
from logger import get_logger

logger = get_logger()

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> UserInDB:
    """
    Получить текущего пользователя из JWT токена.

    Args:
        credentials: HTTP Bearer токен
        session: Database session

    Returns:
        UserInDB: Текущий пользователь

    Raises:
        HTTPException: Если токен невалиден или пользователь не найден
    """
    token = credentials.credentials

    payload = JWTHelper.verify_token(token, token_type="access")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


async def get_current_active_user(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    """
    Получить текущего активного пользователя.

    Args:
        current_user: Текущий пользователь

    Returns:
        UserInDB: Активный пользователь

    Raises:
        HTTPException: Если пользователь неактивен
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


async def get_current_superuser(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    """
    Получить текущего суперпользователя.

    Args:
        current_user: Текущий пользователь

    Returns:
        UserInDB: Суперпользователь

    Raises:
        HTTPException: Если пользователь не является суперпользователем
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    return current_user


async def check_user_quotas(
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserInDB:
    """
    Проверить квоты пользователя.

    Args:
        current_user: Текущий пользователь
        session: Database session

    Returns:
        UserInDB: Пользователь

    Raises:
        HTTPException: Если квоты исчерпаны
    """
    quota_repo = UserQuotaRepository(session)
    quota = await quota_repo.get_by_user_id(current_user.id)

    if not quota:
        quota_create = UserQuotaCreate(
            user_id=current_user.id,
            max_recordings_per_month=100,
            max_storage_gb=50,
            max_concurrent_tasks=3,
        )
        quota = await quota_repo.create(quota_data=quota_create)

    if quota.current_recordings_count >= quota.max_recordings_per_month:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly recording limit exceeded ({quota.max_recordings_per_month})",
        )

    if quota.current_tasks_count >= quota.max_concurrent_tasks:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Concurrent tasks limit exceeded ({quota.max_concurrent_tasks})",
        )

    return current_user
