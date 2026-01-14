"""Admin endpoint dependencies"""

from fastapi import Depends, HTTPException, status

from api.auth.dependencies import get_current_user
from api.schemas.auth import UserInDB
from logger import get_logger

logger = get_logger()


async def get_current_admin(
    current_user: UserInDB = Depends(get_current_user),
) -> UserInDB:
    """
    Получить текущего пользователя с ролью admin.

    Args:
        current_user: Текущий пользователь

    Returns:
        UserInDB: Пользователь с ролью admin

    Raises:
        HTTPException: Если пользователь не является админом
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user

