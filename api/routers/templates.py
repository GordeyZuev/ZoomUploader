"""API endpoints для работы с шаблонами записей."""


from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_active_user
from api.dependencies import get_db_session
from api.repositories.template_repos import RecordingTemplateRepository
from api.schemas.template import (
    RecordingTemplateCreate,
    RecordingTemplateResponse,
    RecordingTemplateUpdate,
)
from database.auth_models import UserModel

router = APIRouter(prefix="/api/v1/templates", tags=["Templates"])


@router.get("", response_model=list[RecordingTemplateResponse])
async def list_templates(
    include_drafts: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение списка шаблонов пользователя."""
    repo = RecordingTemplateRepository(session)
    templates = await repo.find_by_user(current_user.id, include_drafts=include_drafts)
    return templates


@router.get("/{template_id}", response_model=RecordingTemplateResponse)
async def get_template(
    template_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение шаблона по ID."""
    repo = RecordingTemplateRepository(session)
    template = await repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    return template


@router.post("", response_model=RecordingTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: RecordingTemplateCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Создание нового шаблона."""
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create templates"
        )

    repo = RecordingTemplateRepository(session)
    template = await repo.create(
        user_id=current_user.id,
        name=data.name,
        description=data.description,
        matching_rules=data.matching_rules,
        priority=data.priority,
        processing_config=data.processing_config,
        metadata_config=data.metadata_config,
        output_config=data.output_config,
        is_draft=data.is_draft,
    )

    await session.commit()
    return template


@router.patch("/{template_id}", response_model=RecordingTemplateResponse)
async def update_template(
    template_id: int,
    data: RecordingTemplateUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Обновление шаблона."""
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to update templates"
        )

    repo = RecordingTemplateRepository(session)
    template = await repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(template, field, value)

    await repo.update(template)
    await session.commit()

    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Удаление шаблона."""
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete templates"
        )

    repo = RecordingTemplateRepository(session)
    template = await repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    await repo.delete(template)
    await session.commit()

