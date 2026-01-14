"""API endpoints для работы с пресетами выгрузки."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_active_user
from api.dependencies import get_db_session
from api.repositories.template_repos import OutputPresetRepository
from api.schemas.template import (
    OutputPresetCreate,
    OutputPresetResponse,
    OutputPresetUpdate,
)
from database.auth_models import UserModel

router = APIRouter(prefix="/api/v1/presets", tags=["Output Presets"])


@router.get("", response_model=list[OutputPresetResponse])
async def list_presets(
    platform: str | None = None,
    active_only: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение списка пресетов пользователя."""
    repo = OutputPresetRepository(session)

    if platform:
        presets = await repo.find_by_platform(current_user.id, platform)
    elif active_only:
        presets = await repo.find_active_by_user(current_user.id)
    else:
        presets = await repo.find_by_user(current_user.id)

    return presets


@router.get("/{preset_id}", response_model=OutputPresetResponse)
async def get_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение пресета по ID."""
    repo = OutputPresetRepository(session)
    preset = await repo.find_by_id(preset_id, current_user.id)

    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preset {preset_id} not found"
        )

    return preset


@router.post("", response_model=OutputPresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(
    data: OutputPresetCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Создание нового пресета."""
    repo = OutputPresetRepository(session)
    preset = await repo.create(
        user_id=current_user.id,
        name=data.name,
        platform=data.platform,
        credential_id=data.credential_id,
        preset_metadata=data.preset_metadata.model_dump(exclude_none=True),
        description=data.description,
    )

    await session.commit()
    return preset


@router.patch("/{preset_id}", response_model=OutputPresetResponse)
async def update_preset(
    preset_id: int,
    data: OutputPresetUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Обновление пресета."""
    repo = OutputPresetRepository(session)
    preset = await repo.find_by_id(preset_id, current_user.id)

    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preset {preset_id} not found"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(preset, field, value)

    await repo.update(preset)
    await session.commit()

    return preset


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Удаление пресета."""
    repo = OutputPresetRepository(session)
    preset = await repo.find_by_id(preset_id, current_user.id)

    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preset {preset_id} not found"
        )

    await repo.delete(preset)
    await session.commit()

