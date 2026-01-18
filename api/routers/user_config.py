import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_active_user
from api.dependencies import get_db_session
from api.repositories.config_repos import UserConfigRepository
from api.schemas.config.user_config import UserConfigResponse, UserConfigUpdate
from database.auth_models import UserModel
from logger import get_logger

router = APIRouter(prefix="/api/v1/users/me/config", tags=["User Config"])
logger = get_logger()


def load_default_config() -> dict:
    config_path = Path(__file__).parent.parent.parent / "config" / "default_user_config.json"
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.get("", response_model=UserConfigResponse)
async def get_user_config(
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    repo = UserConfigRepository(session)
    config = await repo.get_by_user_id(current_user.id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User config not found")

    return config


@router.patch("", response_model=UserConfigResponse)
async def update_user_config(
    update_data: UserConfigUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    repo = UserConfigRepository(session)
    config = await repo.get_by_user_id(current_user.id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User config not found")

    current_config = config.config_data
    update_dict = update_data.model_dump(exclude_unset=True)

    merged_config = deep_merge(current_config, update_dict)

    updated_config = await repo.update(config, merged_config)
    await session.commit()

    logger.info(f"User config updated: user_id={current_user.id}")

    return updated_config


@router.post("/reset", response_model=UserConfigResponse)
async def reset_user_config(
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    repo = UserConfigRepository(session)
    config = await repo.get_by_user_id(current_user.id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User config not found")

    default_config = load_default_config()
    updated_config = await repo.update(config, default_config)
    await session.commit()

    logger.info(f"User config reset to defaults: user_id={current_user.id}")

    return updated_config
