"""Endpoints для аутентификации и управления пользователями."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_user
from api.auth.security import JWTHelper, PasswordHelper
from api.config import get_settings
from api.dependencies import get_db_session
from api.repositories.auth_repos import (
    RefreshTokenRepository,
    UserQuotaRepository,
    UserRepository,
)
from api.schemas.auth import (
    LoginRequest,
    RefreshTokenCreate,
    RefreshTokenRequest,
    RegisterRequest,
    TokenPair,
    UserCreate,
    UserInDB,
    UserQuotaCreate,
    UserResponse,
    UserUpdate,
)
from api.schemas.auth.response import MeResponse
from logger import get_logger

logger = get_logger()
settings = get_settings()

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: AsyncSession = Depends(get_db_session)):
    """
    Регистрация нового пользователя.

    Args:
        request: Данные для регистрации
        session: Database session

    Returns:
        Информация о созданном пользователе

    Raises:
        HTTPException: Если email уже существует
    """
    user_repo = UserRepository(session)
    quota_repo = UserQuotaRepository(session)

    existing_user = await user_repo.get_by_email(request.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    hashed_password = PasswordHelper.hash_password(request.password)

    user_create = UserCreate(
        email=request.email,
        password=request.password,
        full_name=request.full_name,
    )

    user = await user_repo.create(user_data=user_create, hashed_password=hashed_password)

    quota_create = UserQuotaCreate(
        user_id=user.id,
        max_recordings_per_month=100,
        max_storage_gb=50,
        max_concurrent_tasks=3,
    )
    await quota_repo.create(quota_data=quota_create)

    logger.info(f"New user registered: {user.email} (ID: {user.id})")

    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenPair)
async def login(request: LoginRequest, session: AsyncSession = Depends(get_db_session)):
    """
    Вход в систему.

    Args:
        request: Данные для входа
        session: Database session

    Returns:
        Access и refresh токены

    Raises:
        HTTPException: Если учетные данные неверны
    """
    user_repo = UserRepository(session)
    token_repo = RefreshTokenRepository(session)

    user = await user_repo.get_by_email(request.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not PasswordHelper.verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    access_token = JWTHelper.create_access_token({"user_id": user.id, "email": user.email})
    refresh_token = JWTHelper.create_refresh_token({"user_id": user.id})

    expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)

    token_create = RefreshTokenCreate(
        user_id=user.id,
        token=refresh_token,
        expires_at=expires_at,
    )
    await token_repo.create(token_data=token_create)

    user_update = UserUpdate(last_login_at=datetime.utcnow())
    await user_repo.update(user.id, user_update)

    logger.info(f"User logged in: {user.email} (ID: {user.id})")

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(request: RefreshTokenRequest, session: AsyncSession = Depends(get_db_session)):
    """
    Обновление access токена с помощью refresh токена.

    Args:
        request: Refresh токен
        session: Database session

    Returns:
        Новые access и refresh токены

    Raises:
        HTTPException: Если токен невалиден
    """
    user_repo = UserRepository(session)
    token_repo = RefreshTokenRepository(session)

    payload = JWTHelper.verify_token(request.refresh_token, token_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    token_exists = await token_repo.get_by_token(request.refresh_token)
    if not token_exists or token_exists.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked or not found",
        )

    user = await user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not found or inactive",
        )

    new_access_token = JWTHelper.create_access_token({"user_id": user.id, "email": user.email})
    new_refresh_token = JWTHelper.create_refresh_token({"user_id": user.id})

    await token_repo.revoke(request.refresh_token)

    expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)

    token_create = RefreshTokenCreate(
        user_id=user.id,
        token=new_refresh_token,
        expires_at=expires_at,
    )
    await token_repo.create(token_data=token_create)

    logger.info(f"Token refreshed for user: {user.email} (ID: {user.id})")

    return TokenPair(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(request: RefreshTokenRequest, session: AsyncSession = Depends(get_db_session)):
    """
    Выход из системы (отзыв refresh токена).

    Args:
        request: Refresh токен
        session: Database session

    Returns:
        Подтверждение выхода
    """
    token_repo = RefreshTokenRepository(session)
    await token_repo.revoke(request.refresh_token)
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=MeResponse)
async def get_me(
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Получить информацию о текущем пользователе.

    Требует аутентификации через JWT токен.

    Args:
        current_user: Текущий пользователь (из JWT токена)
        session: Database session

    Returns:
        Информация о пользователе и его квотах
    """
    quota_repo = UserQuotaRepository(session)

    quota = await quota_repo.get_by_user_id(current_user.id)
    quotas_dict = None
    if quota:
        quotas_dict = {
            "max_recordings_per_month": quota.max_recordings_per_month,
            "max_storage_gb": quota.max_storage_gb,
            "max_concurrent_tasks": quota.max_concurrent_tasks,
            "current_recordings_count": quota.current_recordings_count,
            "current_storage_gb": quota.current_storage_gb,
            "current_tasks_count": quota.current_tasks_count,
            "quota_reset_at": quota.quota_reset_at.isoformat(),
        }

    return MeResponse(
        user=UserResponse.model_validate(current_user),
        quotas=quotas_dict,
    )
