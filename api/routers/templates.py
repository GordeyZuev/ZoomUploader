"""Recording template endpoints"""


from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from logger import get_logger
from models.recording import ProcessingStatus

router = APIRouter(prefix="/api/v1/templates", tags=["Templates"])
logger = get_logger()


@router.get("", response_model=list[RecordingTemplateResponse])
async def list_templates(
    search: str | None = Query(None, description="Search substring in template name (case-insensitive)"),
    include_drafts: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение списка шаблонов пользователя."""
    repo = RecordingTemplateRepository(session)
    templates = await repo.find_by_user(current_user.id, include_drafts=include_drafts)

    # Apply search filter
    if search:
        search_lower = search.lower()
        templates = [t for t in templates if search_lower in t.name.lower()]

    return templates


@router.post("", response_model=RecordingTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: RecordingTemplateCreate,
    auto_rematch: bool = Query(
        True, description="Автоматически re-match SKIPPED recordings после создания template"
    ),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Создание нового шаблона.

    Args:
        data: Данные template
        auto_rematch: Автоматически запустить re-match для SKIPPED recordings (default: True)
        session: DB session
        current_user: Текущий пользователь

    Returns:
        Созданный template

    Note:
        Если auto_rematch=True и template не draft, автоматически запускается background task
        для проверки всех SKIPPED recordings и обновления тех, что matched к новому template.
    """
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
        matching_rules=data.matching_rules.model_dump(exclude_none=True) if data.matching_rules else None,
        processing_config=data.processing_config.model_dump(exclude_none=True) if data.processing_config else None,
        metadata_config=data.metadata_config.model_dump(exclude_none=True) if data.metadata_config else None,
        output_config=data.output_config.model_dump(exclude_none=True) if data.output_config else None,
        is_draft=data.is_draft,
    )

    await session.commit()
    await session.refresh(template)

    # Автоматический re-match если не draft и auto_rematch=True
    logger.info(
        f"Template {template.id} created: is_draft={template.is_draft}, "
        f"is_active={template.is_active}, auto_rematch={auto_rematch}"
    )

    if auto_rematch and not template.is_draft and template.is_active:
        # Import rematch task
        from api.tasks.template import rematch_recordings_task

        task = rematch_recordings_task.delay(
            template_id=template.id,
            user_id=current_user.id,
            only_unmapped=True,
        )

        logger.info(
            f"Queued auto re-match task {task.id} for template {template.id} '{template.name}'"
        )
    else:
        logger.warning(
            f"Skipping auto re-match for template {template.id}: "
            f"auto_rematch={auto_rematch}, is_draft={template.is_draft}, is_active={template.is_active}"
        )

    return template


@router.post("/from-recording/{recording_id}", response_model=RecordingTemplateResponse)
async def create_template_from_recording(
    recording_id: int,
    name: str,
    description: str | None = None,
    match_pattern: str | None = None,
    match_source_id: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Создать template из существующего recording.

    Автоматически заполняет:
    - matching_rules из параметра match_pattern или exact match по display_name
    - matching_rules.source_ids если match_source_id=True
    - Конфигурация: если у recording есть processing_preferences, использует их

    Args:
        recording_id: ID записи
        name: Название template
        description: Описание (опционально)
        match_pattern: Custom matching pattern (опционально)
        match_source_id: Включить source_id в matching rules
        session: DB session
        current_user: Текущий пользователь

    Returns:
        Созданный template
    """
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to create templates"
        )

    from api.repositories.recording_repos import RecordingAsyncRepository
    from database.template_models import RecordingTemplateModel

    recording_repo = RecordingAsyncRepository(session)

    # Get recording
    recording = await recording_repo.get_by_id(recording_id, current_user.id)
    if not recording:
        raise HTTPException(
            status_code=404,
            detail=f"Recording {recording_id} not found"
        )

    # Build matching rules
    matching_rules = {}

    if match_pattern:
        matching_rules["patterns"] = [match_pattern]
    else:
        # Default: exact match
        matching_rules["exact_matches"] = [recording.display_name]

    if match_source_id and recording.input_source_id:
        matching_rules["source_ids"] = [recording.input_source_id]

    # Extract configs if recording has manual preferences
    processing_config = None
    metadata_config = None
    output_config = None

    if recording.processing_preferences:
        processing_config = recording.processing_preferences.get("processing_config")
        metadata_config = recording.processing_preferences.get("metadata_config")
        output_config = recording.processing_preferences.get("output_config")

    # Create template
    template = RecordingTemplateModel(
        user_id=current_user.id,
        name=name,
        description=description or f"Created from recording '{recording.display_name}'",
        matching_rules=matching_rules,
        processing_config=processing_config,
        metadata_config=metadata_config,
        output_config=output_config,
        is_active=True,
        is_draft=False,
    )

    session.add(template)
    await session.commit()
    await session.refresh(template)

    return template


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
    """
    Удаление шаблона.

    При удалении template автоматически:
    - Все записи с этим template unmapped (template_id → NULL, is_mapped → False)
    - Записи не меняют свой status, но становятся доступны для нового matching

    Note:
        Удаление аналогично созданию: при создании template происходит auto-rematch,
        при удалении - автоматический unmap всех связанных записей.
    """
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

    # Получаем количество mapped recordings для логирования
    from sqlalchemy import select, update

    from database.models import RecordingModel

    # Считаем количество affected recordings
    count_query = select(RecordingModel).where(
        RecordingModel.template_id == template_id,
        RecordingModel.user_id == current_user.id
    )
    result = await session.execute(count_query)
    affected_count = len(result.scalars().all())

    # Unmapping всех recordings с этим template
    if affected_count > 0:
        update_query = (
            update(RecordingModel)
            .where(
                RecordingModel.template_id == template_id,
                RecordingModel.user_id == current_user.id
            )
            .values(
                template_id=None,
                is_mapped=False,
            )
        )
        await session.execute(update_query)
        logger.info(
            f"Unmapped {affected_count} recordings from template {template_id} '{template.name}' "
            f"(user {current_user.id})"
        )

    # Удаляем template
    await repo.delete(template)
    await session.commit()

    logger.info(
        f"Deleted template {template_id} '{template.name}' (user {current_user.id}), "
        f"unmapped {affected_count} recordings"
    )


@router.get("/{template_id}/stats")
async def get_template_stats(
    template_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Статистика использования template:
    - total_recordings: сколько recordings привязано
    - by_status: разбивка по ProcessingStatus
    - last_matched_at: когда последний раз matched (last created_at)

    Args:
        template_id: ID template
        session: DB session
        current_user: Текущий пользователь

    Returns:
        Статистика template
    """
    from sqlalchemy import func, select

    from database.models import RecordingModel

    template_repo = RecordingTemplateRepository(session)

    # Get template
    template = await template_repo.find_by_id(template_id, current_user.id)
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_id} not found"
        )

    # Count total recordings
    count_query = (
        select(func.count(RecordingModel.id))
        .where(RecordingModel.user_id == current_user.id)
        .where(RecordingModel.template_id == template_id)
    )
    count_result = await session.execute(count_query)
    total_recordings = count_result.scalar_one()

    # Count by status
    status_query = (
        select(RecordingModel.status, func.count(RecordingModel.id))
        .where(RecordingModel.user_id == current_user.id)
        .where(RecordingModel.template_id == template_id)
        .group_by(RecordingModel.status)
    )
    status_result = await session.execute(status_query)
    by_status = {row[0]: row[1] for row in status_result}

    # Get last matched recording
    last_matched_query = (
        select(RecordingModel.created_at)
        .where(RecordingModel.user_id == current_user.id)
        .where(RecordingModel.template_id == template_id)
        .order_by(RecordingModel.created_at.desc())
        .limit(1)
    )
    last_matched_result = await session.execute(last_matched_query)
    last_matched_row = last_matched_result.first()
    last_matched_at = last_matched_row[0].isoformat() if last_matched_row else None

    return {
        "template_id": template_id,
        "template_name": template.name,
        "total_recordings": total_recordings,
        "by_status": by_status,
        "last_matched_at": last_matched_at,
        "is_active": template.is_active,
    }


@router.post("/{template_id}/preview")
async def preview_template_match(
    template_id: int,
    only_skipped: bool = Query(True, description="Только SKIPPED recordings (default: True). False = все unmapped."),
    source_id: int | None = Query(None, description="Фильтр по источнику (опционально)"),
    limit: int = Query(100, le=500, description="Максимум recordings для проверки"),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Preview: какие recordings будут matched/re-matched этим template.

    Два режима:
    - only_skipped=True: Проверяет SKIPPED recordings (status=SKIPPED, is_mapped=False)
    - only_skipped=False: Проверяет все unmapped recordings (is_mapped=False)

    Не изменяет данные, только показывает что будет обновлено при rematch.
    Полезно для проверки перед активацией template или изменением matching_rules.

    Args:
        template_id: ID template
        only_skipped: Только SKIPPED или все unmapped (default: True)
        source_id: Фильтр по источнику (опционально)
        limit: Максимум recordings для проверки (default: 100, max: 500)
        session: DB session
        current_user: Текущий пользователь

    Returns:
        Список recordings, которые будут matched, с детальной информацией

    Example response:
        {
            "template_id": 1,
            "template_name": "ИИ Course",
            "mode": "skipped_only",
            "total_checked": 50,
            "will_match_count": 12,
            "will_match": [
                {
                    "id": 44,
                    "display_name": "ИИ_1 курс_Анализ временных рядов",
                    "current_status": "SKIPPED",
                    "current_is_mapped": false,
                    "will_become_status": "INITIALIZED",
                    "will_become_is_mapped": true,
                    "start_time": "2025-12-11T15:05:22+00:00"
                }
            ]
        }

    Note:
        Используйте POST /api/v1/templates/{id}/rematch для реального применения.
    """
    from sqlalchemy import select

    from database.models import RecordingModel

    template_repo = RecordingTemplateRepository(session)

    # Get template
    template = await template_repo.find_by_id(template_id, current_user.id)
    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Template {template_id} not found"
        )

    # Build query для проверки
    query = select(RecordingModel).where(RecordingModel.user_id == current_user.id)

    # Фильтр по unmapped/SKIPPED
    if only_skipped:
        query = query.where(
            RecordingModel.is_mapped == False,  # noqa: E712
            RecordingModel.status == ProcessingStatus.SKIPPED,
        )
    else:
        query = query.where(RecordingModel.is_mapped == False)  # noqa: E712

    # Фильтр по source_id (опционально)
    if source_id:
        query = query.where(RecordingModel.input_source_id == source_id)

    query = query.order_by(RecordingModel.created_at.desc()).limit(limit)

    result = await session.execute(query)
    recordings = result.scalars().all()

    # Test matching
    from api.routers.input_sources import _find_matching_template

    will_match = []
    for recording in recordings:
        matched = _find_matching_template(
            display_name=recording.display_name,
            source_id=recording.input_source_id or 0,
            templates=[template],
        )

        if matched:
            will_match.append(
                {
                    "id": recording.id,
                    "display_name": recording.display_name,
                    "current_status": recording.status.value,
                    "current_is_mapped": recording.is_mapped,
                    "will_become_status": "INITIALIZED",
                    "will_become_is_mapped": True,
                    "start_time": recording.start_time.isoformat(),
                    "duration": recording.duration,
                    "input_source_id": recording.input_source_id,
                }
            )

    return {
        "template_id": template_id,
        "template_name": template.name,
        "mode": "skipped_only" if only_skipped else "all_unmapped",
        "total_checked": len(recordings),
        "will_match_count": len(will_match),
        "will_match": will_match,
        "note": "This is a preview. No data has been changed. Use POST /api/v1/templates/{id}/rematch to apply.",
    }


@router.post("/{template_id}/rematch")
async def rematch_template_recordings(
    template_id: int,
    only_unmapped: bool = Query(
        True, description="Только unmapped (SKIPPED) recordings. False = проверить все recordings."
    ),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Вручную запустить re-match recordings для template.

    Проверяет все SKIPPED (unmapped) recordings и обновляет те, что matched к template.
    Обновляет is_mapped=True, template_id и status=INITIALIZED.

    Use cases:
    - После изменения matching_rules template
    - Для старых recordings, которые появились до создания template
    - Периодическая проверка unmapped recordings

    Args:
        template_id: ID template
        only_unmapped: Проверять только unmapped recordings (default: True)
        session: DB session
        current_user: Текущий пользователь

    Returns:
        Task ID для проверки статуса выполнения

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса и получения результатов.
    """
    template_repo = RecordingTemplateRepository(session)
    template = await template_repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_id} not found"
        )

    if not template.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template {template_id} is not active. Cannot re-match.",
        )

    if template.is_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template {template_id} is draft. Cannot re-match.",
        )

    # Запускаем background task
    from api.tasks.template import rematch_recordings_task

    task = rematch_recordings_task.delay(
        template_id=template_id,
        user_id=current_user.id,
        only_unmapped=only_unmapped,
    )

    logger.info(
        f"Queued manual re-match task {task.id} for template {template_id} "
        f"(only_unmapped={only_unmapped})"
    )

    return {
        "message": "Re-match task queued successfully",
        "task_id": task.id,
        "template_id": template_id,
        "template_name": template.name,
        "only_unmapped": only_unmapped,
        "note": "Use GET /api/v1/tasks/{task_id} to check status",
    }
