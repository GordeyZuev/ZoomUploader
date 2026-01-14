"""Endpoints для управления профилем пользователя."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_user
from api.auth.security import PasswordHelper
from api.dependencies import get_db_session
from api.repositories.auth_repos import (
    RefreshTokenRepository,
    UserRepository,
)
from api.schemas.auth import QuotaStatusResponse, QuotaUsageResponse, UserInDB, UserResponse, UserUpdate
from api.schemas.auth.response import UserMeResponse
from api.schemas.user import (
    AccountDeleteResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    PasswordChangeResponse,
    UserProfileUpdate,
)
from api.services.quota_service import QuotaService
from database.auth_models import (
    RefreshTokenModel,
    UserCredentialModel,
    UserModel,
)
from database.config_models import UserConfigModel
from database.models import (
    OutputTargetModel,
    ProcessingStageModel,
    RecordingModel,
    SourceMetadataModel,
)
from database.template_models import (
    InputSourceModel,
    OutputPresetModel,
    RecordingTemplateModel,
)
from logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/users", tags=["User Management"])


@router.get("/me", response_model=UserMeResponse)
async def get_me(
    current_user: UserInDB = Depends(get_current_user),
):
    """
    Получить базовую информацию о текущем пользователе.

    Для получения информации о квотах используйте GET /api/v1/users/me/quota

    Требует аутентификации через JWT токен.

    Args:
        current_user: Текущий пользователь (из JWT токена)

    Returns:
        Базовая информация о пользователе
    """
    return UserMeResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        timezone=current_user.timezone,
        role=current_user.role,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
        last_login_at=current_user.last_login_at,
    )


@router.get("/me/quota", response_model=QuotaStatusResponse)
async def get_my_quota(
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Получить текущий статус квот пользователя.

    Включает:
    - Информацию о подписке и плане
    - Эффективные квоты (с учетом custom overrides)
    - Текущее использование за период
    - Доступные ресурсы (available/limit)
    - Pay-as-you-go статус и overage cost

    Требует аутентификации через JWT токен.

    Args:
        current_user: Текущий пользователь (из JWT токена)
        session: Database session

    Returns:
        QuotaStatusResponse: Полный статус квот

    Raises:
        HTTPException: Если подписка не найдена
    """
    quota_service = QuotaService(session)

    try:
        quota_status = await quota_service.get_quota_status(current_user.id)
        return quota_status
    except ValueError as e:
        logger.error(f"Error getting quota status for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/me/quota/history", response_model=list[QuotaUsageResponse])
async def get_my_quota_history(
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    limit: int = Query(12, ge=1, le=24, description="Количество периодов (макс 24)"),
    period: int | None = Query(
        None,
        description="Конкретный период (YYYYMM), если None - последние N периодов",
    ),
):
    """
    Получить историю использования квот.

    По умолчанию возвращает последние 12 периодов.
    Можно запросить конкретный период или задать лимит.

    Args:
        current_user: Текущий пользователь (из JWT токена)
        session: Database session
        limit: Количество периодов для возврата (по умолчанию 12, макс 24)
        period: Конкретный период (YYYYMM), опционально

    Returns:
        list[QuotaUsageResponse]: История использования квот

    Examples:
        - GET /api/v1/users/me/quota/history - последние 12 месяцев
        - GET /api/v1/users/me/quota/history?limit=6 - последние 6 месяцев
        - GET /api/v1/users/me/quota/history?period=202601 - только январь 2026
    """
    quota_service = QuotaService(session)

    # Если указан конкретный период
    if period:
        usage = await quota_service.usage_repo.get_by_user_and_period(current_user.id, period)
        if not usage:
            # Вернуть пустой список, если период не найден
            return []

        return [
            QuotaUsageResponse(
                period=usage.period,
                recordings_count=usage.recordings_count,
                storage_gb=usage.storage_bytes / (1024**3),
                concurrent_tasks_count=usage.concurrent_tasks_count,
                overage_recordings_count=usage.overage_recordings_count,
                overage_cost=usage.overage_cost,
            )
        ]

    # Иначе возвращаем историю
    usages = await quota_service.usage_repo.get_history(current_user.id, limit=limit)

    return [
        QuotaUsageResponse(
            period=usage.period,
            recordings_count=usage.recordings_count,
            storage_gb=usage.storage_bytes / (1024**3),
            concurrent_tasks_count=usage.concurrent_tasks_count,
            overage_recordings_count=usage.overage_recordings_count,
            overage_cost=usage.overage_cost,
        )
        for usage in usages
    ]


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    profile_data: UserProfileUpdate,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Обновить профиль текущего пользователя.

    Пользователь может обновить:
    - full_name - полное имя
    - email - email адрес

    Args:
        profile_data: Данные для обновления
        current_user: Текущий пользователь (из JWT токена)
        session: Database session

    Returns:
        Обновленная информация о пользователе

    Raises:
        HTTPException: Если email уже используется другим пользователем
    """
    user_repo = UserRepository(session)

    # Проверяем, что email не занят другим пользователем
    if profile_data.email and profile_data.email != current_user.email:
        existing_user = await user_repo.get_by_email(profile_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use by another user",
            )

    # Обновляем только те поля, которые были переданы
    user_update = UserUpdate(
        email=profile_data.email,
        full_name=profile_data.full_name,
    )

    updated_user = await user_repo.update(current_user.id, user_update)
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(f"User profile updated: {updated_user.email} (ID: {updated_user.id})")

    return UserResponse.model_validate(updated_user)


@router.post("/me/password", response_model=PasswordChangeResponse, status_code=status.HTTP_200_OK)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PasswordChangeResponse:
    """
    Сменить пароль текущего пользователя.

    Args:
        password_data: Текущий и новый пароль
        current_user: Текущий пользователь (из JWT токена)
        session: Database session

    Returns:
        Подтверждение смены пароля

    Raises:
        HTTPException: Если текущий пароль неверен
    """
    # Проверяем текущий пароль
    if not PasswordHelper.verify_password(password_data.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Проверяем, что новый пароль отличается от старого
    if PasswordHelper.verify_password(password_data.new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    # Хешируем новый пароль
    new_hashed_password = PasswordHelper.hash_password(password_data.new_password)

    # Обновляем пароль в БД
    result = await session.execute(select(UserModel).where(UserModel.id == current_user.id))
    db_user = result.scalars().first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    db_user.hashed_password = new_hashed_password
    await session.commit()

    # Отзываем все refresh токены (выход на всех устройствах)
    token_repo = RefreshTokenRepository(session)
    result = await session.execute(select(RefreshTokenModel).where(RefreshTokenModel.user_id == current_user.id))
    tokens = result.scalars().all()
    for token in tokens:
        await token_repo.revoke(token.token)

    logger.info(f"Password changed for user: {current_user.email} (ID: {current_user.id})")

    return PasswordChangeResponse(
        message="Password changed successfully",
        detail="All active sessions have been terminated. Please login again.",
    )


@router.delete("/me", response_model=AccountDeleteResponse, status_code=status.HTTP_200_OK)
async def delete_account(
    delete_data: DeleteAccountRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AccountDeleteResponse:
    """
    Удалить аккаунт текущего пользователя.

    ⚠️ ВНИМАНИЕ: Это действие необратимо!

    Будут удалены:
    - Профиль пользователя
    - Все recordings
    - Все credentials
    - Все presets и templates
    - Все токены

    Args:
        delete_data: Пароль и подтверждение удаления
        current_user: Текущий пользователь (из JWT токена)
        session: Database session

    Returns:
        Подтверждение удаления

    Raises:
        HTTPException: Если пароль неверен или подтверждение не прошло
    """
    # Проверяем пароль
    if not PasswordHelper.verify_password(delete_data.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password",
        )

    user_id = current_user.id
    user_email = current_user.email

    # Удаляем все связанные данные (в правильном порядке из-за FK)
    # 1. Output targets
    await session.execute(select(OutputTargetModel).where(OutputTargetModel.user_id == user_id))
    result = await session.execute(select(OutputTargetModel).where(OutputTargetModel.user_id == user_id))
    output_targets = result.scalars().all()
    for target in output_targets:
        await session.delete(target)

    # 2. Processing stages
    result = await session.execute(select(ProcessingStageModel).where(ProcessingStageModel.user_id == user_id))
    stages = result.scalars().all()
    for stage in stages:
        await session.delete(stage)

    # 3. Source metadata
    result = await session.execute(select(SourceMetadataModel).where(SourceMetadataModel.user_id == user_id))
    sources = result.scalars().all()
    for source in sources:
        await session.delete(source)

    # 4. Recordings
    result = await session.execute(select(RecordingModel).where(RecordingModel.user_id == user_id))
    recordings = result.scalars().all()
    for recording in recordings:
        await session.delete(recording)

    # 5. Templates
    result = await session.execute(select(RecordingTemplateModel).where(RecordingTemplateModel.user_id == user_id))
    templates = result.scalars().all()
    for template in templates:
        await session.delete(template)

    # 6. Output presets
    result = await session.execute(select(OutputPresetModel).where(OutputPresetModel.user_id == user_id))
    presets = result.scalars().all()
    for preset in presets:
        await session.delete(preset)

    # 7. Input sources
    result = await session.execute(select(InputSourceModel).where(InputSourceModel.user_id == user_id))
    input_sources = result.scalars().all()
    for input_source in input_sources:
        await session.delete(input_source)

    # 8. User config
    result = await session.execute(select(UserConfigModel).where(UserConfigModel.user_id == user_id))
    user_config = result.scalars().first()
    if user_config:
        await session.delete(user_config)

    # 9. Credentials
    result = await session.execute(select(UserCredentialModel).where(UserCredentialModel.user_id == user_id))
    credentials = result.scalars().all()
    for credential in credentials:
        await session.delete(credential)

    # 10. Refresh tokens
    result = await session.execute(select(RefreshTokenModel).where(RefreshTokenModel.user_id == user_id))
    tokens = result.scalars().all()
    for token in tokens:
        await session.delete(token)

    # 11. User (последним!) - subscriptions and quotas will be deleted via CASCADE
    result = await session.execute(select(UserModel).where(UserModel.id == user_id))
    db_user = result.scalars().first()
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await session.delete(db_user)
    await session.commit()

    logger.info(f"Account deleted: {user_email} (ID: {user_id})")

    return AccountDeleteResponse(
        message="Account successfully deleted",
        detail="All your data has been permanently removed from our system.",
    )

