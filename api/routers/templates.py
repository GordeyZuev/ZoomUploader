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
    """Get list of user's templates."""
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
    auto_rematch: bool = Query(True, description="Automatically re-match SKIPPED recordings after creating template"),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Create new template.

    Args:
        data: Данные template
        auto_rematch: Automatically start re-match for SKIPPED recordings (default: True)
        session: DB session
        current_user: Current user

    Returns:
        Created template

    Note:
        If auto_rematch=True and template is not draft, a background task will be started
        to check all SKIPPED recordings and update those that matched to the new template.
    """
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to create templates"
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

    # Automatic re-match if not draft and auto_rematch=True
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

        logger.info(f"Queued auto re-match task {task.id} for template {template.id} '{template.name}'")
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
    Create template from existing recording.

    Automatically fills:
    - matching_rules from match_pattern parameter or exact match by display_name
    - matching_rules.source_ids if match_source_id=True
    - Configuration: if recording has processing_preferences, use them

    Args:
        recording_id: ID of recording
        name: Name of template
        description: Description (optional)
        match_pattern: Custom matching pattern (optional)
        match_source_id: Include source_id in matching rules
        session: DB session
        current_user: Current user

    Returns:
        Created template
    """
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to create templates"
        )

    from api.repositories.recording_repos import RecordingAsyncRepository
    from database.template_models import RecordingTemplateModel

    recording_repo = RecordingAsyncRepository(session)

    # Get recording
    recording = await recording_repo.get_by_id(recording_id, current_user.id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

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
    """Get template by ID."""
    repo = RecordingTemplateRepository(session)
    template = await repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_id} not found")

    return template


@router.patch("/{template_id}", response_model=RecordingTemplateResponse)
async def update_template(
    template_id: int,
    data: RecordingTemplateUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Update template."""
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to update templates"
        )

    repo = RecordingTemplateRepository(session)
    template = await repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_id} not found")

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
    Delete template.

    When template is deleted, all recordings with this template are unmapped (template_id → NULL, is_mapped → False)
    - Recordings do not change their status, but become available for new matching

    Note:
        Deletion is similar to creation: when template is created, auto-rematch is started,
        when deleted - automatically unmap all related recordings.
    """
    if not current_user.can_create_templates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to delete templates"
        )

    repo = RecordingTemplateRepository(session)
    template = await repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_id} not found")

    # Get number of mapped recordings for logging
    from sqlalchemy import select, update

    from database.models import RecordingModel

    # Count number of affected recordings
    count_query = select(RecordingModel).where(
        RecordingModel.template_id == template_id, RecordingModel.user_id == current_user.id
    )
    result = await session.execute(count_query)
    affected_count = len(result.scalars().all())

    # Unmapping all recordings with this template
    if affected_count > 0:
        update_query = (
            update(RecordingModel)
            .where(RecordingModel.template_id == template_id, RecordingModel.user_id == current_user.id)
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

    # Delete template
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
) -> dict:
    """
    Statistics of template usage:
    - total_recordings: how many recordings are mapped
    - by_status: breakdown by ProcessingStatus
    - last_matched_at: when last matched (last created_at)

    Args:
        template_id: ID of template
        session: DB session
        current_user: Current user

    Returns:
        Statistics of template usage
    """
    from sqlalchemy import func, select

    from database.models import RecordingModel

    template_repo = RecordingTemplateRepository(session)

    # Get template
    template = await template_repo.find_by_id(template_id, current_user.id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

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

    from api.schemas.template.operations import TemplateStatsResponse

    return TemplateStatsResponse(
        template_id=template_id,
        template_name=template.name,
        total_recordings=total_recordings,
        by_status=by_status,
        last_matched_at=last_matched_at,
        is_active=template.is_active,
    )


@router.post("/{template_id}/preview")
async def preview_template_match(
    template_id: int,
    only_skipped: bool = Query(True, description="Only SKIPPED recordings (default: True). False = all unmapped."),
    source_id: int | None = Query(None, description="Filter by source (optional)"),
    limit: int = Query(100, le=500, description="Maximum recordings to check"),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
) -> dict:
    """
    Preview: which recordings will be matched/re-matched by this template.

    Two modes:
    - only_skipped=True: Checks SKIPPED recordings (status=SKIPPED, is_mapped=False)
    - only_skipped=False: Checks all unmapped recordings (is_mapped=False)

    Does not change data, only shows what will be updated when rematching.
    Useful for checking before activating template or changing matching_rules.

    Args:
        template_id: ID of template
        only_skipped: Only SKIPPED or all unmapped (default: True)
        source_id: Filter by source (optional)
        limit: Maximum recordings to check (default: 100, max: 500)
        session: DB session
        current_user: Current user

    Returns:
        List of recordings that will be matched, with detailed information

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
        Use POST /api/v1/templates/{id}/rematch for real application.
    """
    from sqlalchemy import select

    from database.models import RecordingModel

    template_repo = RecordingTemplateRepository(session)

    # Get template
    template = await template_repo.find_by_id(template_id, current_user.id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    # Build query for checking
    query = select(RecordingModel).where(RecordingModel.user_id == current_user.id)

    # Filter by unmapped/SKIPPED
    if only_skipped:
        query = query.where(
            RecordingModel.is_mapped == False,  # noqa: E712
            RecordingModel.status == ProcessingStatus.SKIPPED,
        )
    else:
        query = query.where(RecordingModel.is_mapped == False)  # noqa: E712

    # Filter by source_id (optional)
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

    from api.schemas.template.operations import TemplatePreviewResponse

    return TemplatePreviewResponse(
        template_id=template_id,
        template_name=template.name,
        mode="skipped_only" if only_skipped else "all_unmapped",
        total_checked=len(recordings),
        will_match_count=len(will_match),
        will_match=will_match,
        note="This is a preview. No data has been changed. Use POST /api/v1/templates/{id}/rematch to apply.",
    )


@router.post("/{template_id}/rematch")
async def rematch_template_recordings(
    template_id: int,
    only_unmapped: bool = Query(True, description="Only unmapped (SKIPPED) recordings. False = check all recordings."),
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
) -> dict:
    """
    Manually start re-match recordings for template.

    Checks all SKIPPED (unmapped) recordings and updates those that matched to the template.
    Updates is_mapped=True, template_id and status=INITIALIZED.

    Use cases:
    - After changing matching_rules template
    - For old recordings that appeared before template creation
    - Periodic checking of unmapped recordings

    Args:
        template_id: ID template
        only_unmapped: Check only unmapped recordings (default: True)
        session: DB session
        current_user: Current user

    Returns:
        Task ID for checking status of execution

    Note:
        This is an asynchronous operation. Use GET /api/v1/tasks/{task_id}
        to check status and get results.
    """
    template_repo = RecordingTemplateRepository(session)
    template = await template_repo.find_by_id(template_id, current_user.id)

    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_id} not found")

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

    # Start background task
    from api.tasks.template import rematch_recordings_task

    task = rematch_recordings_task.delay(
        template_id=template_id,
        user_id=current_user.id,
        only_unmapped=only_unmapped,
    )

    logger.info(f"Queued manual re-match task {task.id} for template {template_id} (only_unmapped={only_unmapped})")

    from api.schemas.template.operations import RematchTaskResponse

    return RematchTaskResponse(
        message="Re-match task queued successfully",
        task_id=task.id,
        template_id=template_id,
        template_name=template.name,
        only_unmapped=only_unmapped,
        note="Use GET /api/v1/tasks/{task_id} to check status",
    )
