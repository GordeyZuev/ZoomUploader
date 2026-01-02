"""API endpoints для работы с базовыми конфигурациями."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_active_user
from api.dependencies import get_db_session
from api.repositories.template_repos import BaseConfigRepository
from api.schemas.template import (
    BaseConfigCreate,
    BaseConfigResponse,
    BaseConfigUpdate,
)
from database.auth_models import UserModel

router = APIRouter(prefix="/configs", tags=["configs"])


@router.get("", response_model=list[BaseConfigResponse])
async def list_configs(
    include_global: bool = True,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение списка конфигураций."""
    repo = BaseConfigRepository(session)
    user_configs = await repo.find_by_user(current_user.id)

    if include_global:
        global_configs = await repo.find_global()
        all_configs = global_configs + user_configs
    else:
        all_configs = user_configs

    return [BaseConfigResponse.from_orm_model(c) for c in all_configs]


@router.get("/{config_id}", response_model=BaseConfigResponse)
async def get_config(
    config_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение конфигурации по ID."""
    repo = BaseConfigRepository(session)
    config = await repo.find_by_id(config_id, user_id=current_user.id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config {config_id} not found"
        )

    return BaseConfigResponse.from_orm_model(config)


@router.post("", response_model=BaseConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_config(
    data: BaseConfigCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Создание новой конфигурации."""
    if data.is_global and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create global configs"
        )

    repo = BaseConfigRepository(session)
    config = await repo.create(
        user_id=None if data.is_global else current_user.id,
        name=data.name,
        config_data=data.config_data,
        description=data.description,
        config_type=data.config_type,
    )

    await session.commit()
    return BaseConfigResponse.from_orm_model(config)


@router.patch("/{config_id}", response_model=BaseConfigResponse)
async def update_config(
    config_id: int,
    data: BaseConfigUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Обновление конфигурации."""
    repo = BaseConfigRepository(session)
    config = await repo.find_by_id(config_id, user_id=current_user.id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config {config_id} not found"
        )

    # Проверка прав для глобальной конфигурации
    if config.user_id is None and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update global configs"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await repo.update(config)
    await session.commit()

    return BaseConfigResponse.from_orm_model(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Удаление конфигурации."""
    repo = BaseConfigRepository(session)
    config = await repo.find_by_id(config_id, user_id=current_user.id)

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config {config_id} not found"
        )

    # Проверка прав для глобальной конфигурации
    if config.user_id is None and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete global configs"
        )

    await repo.delete(config)
    await session.commit()

