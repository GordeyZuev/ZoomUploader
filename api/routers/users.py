"""Endpoints для управления профилем пользователя."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_user
from api.auth.security import PasswordHelper
from api.dependencies import get_db_session
from api.repositories.auth_repos import (
    RefreshTokenRepository,
    UserQuotaRepository,
    UserRepository,
)
from api.schemas.auth import UserInDB, UserResponse, UserUpdate
from api.schemas.auth.response import MeResponse
from api.schemas.user import ChangePasswordRequest, DeleteAccountRequest, UserProfileUpdate
from database.auth_models import (
    RefreshTokenModel,
    UserCredentialModel,
    UserModel,
    UserQuotaModel,
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


@router.post("/me/password", status_code=status.HTTP_200_OK)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
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

    return {
        "message": "Password changed successfully",
        "detail": "All active sessions have been terminated. Please login again.",
    }


@router.delete("/me", status_code=status.HTTP_200_OK)
async def delete_account(
    delete_data: DeleteAccountRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
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

    # 11. Quotas
    result = await session.execute(select(UserQuotaModel).where(UserQuotaModel.user_id == user_id))
    quota = result.scalars().first()
    if quota:
        await session.delete(quota)

    # 12. User (последним!)
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

    return {
        "message": "Account successfully deleted",
        "detail": "All your data has been permanently removed from our system.",
    }

