"""API endpoints для работы с источниками данных."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_active_user
from api.dependencies import get_db_session
from api.repositories.auth_repos import UserCredentialRepository
from api.repositories.recording_repos import RecordingAsyncRepository
from api.repositories.template_repos import InputSourceRepository, RecordingTemplateRepository
from api.schemas.template import (
    BatchSyncRequest,
    InputSourceCreate,
    InputSourceResponse,
    InputSourceUpdate,
)
from api.zoom_api import ZoomAPI
from config.settings import ZoomConfig
from database.auth_models import UserModel
from logger import get_logger
from models.recording import SourceType

router = APIRouter(prefix="/api/v1/sources", tags=["Input Sources"])
logger = get_logger()


async def _sync_single_source(
    source_id: int,
    from_date: str,
    to_date: str | None,
    session: AsyncSession,
    user_id: int,
) -> dict:
    """
    Синхронизация одного источника (внутренняя функция для DRY).

    Returns:
        dict с ключами: status, recordings_found, recordings_saved, recordings_updated, error (опционально)
    """
    repo = InputSourceRepository(session)
    source = await repo.find_by_id(source_id, user_id)

    if not source:
        return {
            "status": "error",
            "error": f"Source {source_id} not found",
        }

    if not source.is_active:
        return {
            "status": "error",
            "error": "Source is not active",
        }

    if not source.credential_id:
        return {
            "status": "error",
            "error": "Source has no credential configured",
        }

    # Получаем credentials
    cred_repo = UserCredentialRepository(session)
    credential = await cred_repo.get_by_id(source.credential_id)

    if not credential:
        return {
            "status": "error",
            "error": f"Credentials {source.credential_id} not found",
        }

    from api.auth.encryption import get_encryption
    encryption = get_encryption()
    credentials = encryption.decrypt_credentials(credential.encrypted_data)

    # Синхронизация в зависимости от типа
    meetings = []
    saved_count = 0
    updated_count = 0

    if source.source_type == "ZOOM":
        try:
            # Определяем тип credentials
            if "access_token" in credentials:
                zoom_config = ZoomConfig(
                    account=credentials.get("account", "oauth_user"),
                    account_id="",
                    client_id=credentials.get("client_id", ""),
                    client_secret=credentials.get("client_secret", ""),
                    access_token=credentials.get("access_token"),
                    refresh_token=credentials.get("refresh_token"),
                )
            else:
                zoom_config = ZoomConfig(
                    account=credentials.get("account", ""),
                    account_id=credentials["account_id"],
                    client_id=credentials["client_id"],
                    client_secret=credentials["client_secret"],
                )

            zoom_api = ZoomAPI(zoom_config)
            recordings_data = await zoom_api.get_recordings(from_date=from_date, to_date=to_date)
            meetings = recordings_data.get("meetings", [])

            logger.info(f"Found {len(meetings)} recordings from Zoom source {source_id}")

            # Получаем шаблоны
            template_repo = RecordingTemplateRepository(session)
            templates = await template_repo.find_active_by_user(user_id)

            # Сохраняем recordings
            recording_repo = RecordingAsyncRepository(session)

            for meeting in meetings:
                try:
                    meeting_id = meeting.get("uuid", meeting.get("id", ""))
                    display_name = meeting.get("topic", "Untitled")
                    start_time_str = meeting.get("start_time", "")
                    duration = meeting.get("duration", 0)

                    if start_time_str:
                        if start_time_str.endswith("Z"):
                            start_time_str = start_time_str[:-1] + "+00:00"
                        start_time = datetime.fromisoformat(start_time_str)
                    else:
                        logger.warning(f"Meeting {meeting_id} has no start_time, skipping")
                        continue

                    # Получаем видео файл
                    recording_files = meeting.get("recording_files", [])
                    video_file = None
                    for file in recording_files:
                        if file.get("file_type") == "MP4" and file.get("recording_type") == "shared_screen_with_speaker_view":
                            video_file = file
                            break

                    if not video_file:
                        for file in recording_files:
                            if file.get("file_type") == "MP4":
                                video_file = file
                                break

                    # Получаем download_access_token
                    download_access_token = None
                    meeting_details = None
                    try:
                        meeting_details = await zoom_api.get_recording_details(meeting_id, include_download_token=True)
                        download_access_token = meeting_details.get("download_access_token")
                    except Exception as e:
                        logger.warning(f"Failed to get download_access_token for meeting {meeting_id}: {e}")

                    # Метаданные
                    source_metadata = {
                        "meeting_id": meeting_id,
                        "account": credentials.get("account", ""),
                        "account_id": meeting.get("account_id"),
                        "host_id": meeting.get("host_id"),
                        "host_email": meeting.get("host_email"),
                        "share_url": meeting.get("share_url"),
                        "recording_play_passcode": meeting.get("recording_play_passcode"),
                        "password": meeting.get("password"),
                        "timezone": meeting.get("timezone"),
                        "total_size": meeting.get("total_size"),
                        "recording_count": meeting.get("recording_count"),
                        "download_url": video_file.get("download_url") if video_file else None,
                        "play_url": video_file.get("play_url") if video_file else None,
                        "download_access_token": download_access_token,
                        "video_file_size": video_file.get("file_size") if video_file else None,
                        "video_file_type": video_file.get("file_type") if video_file else None,
                        "recording_type": video_file.get("recording_type") if video_file else None,
                        "delete_time": meeting.get("delete_time"),
                        "auto_delete_date": meeting.get("auto_delete_date"),
                        "zoom_api_meeting": meeting,
                        "zoom_api_details": meeting_details if meeting_details else {},
                    }

                    # Determine if this is a blank record (too short or too small)
                    MIN_DURATION_MINUTES = 20
                    MIN_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

                    video_file_size = video_file.get("file_size") if video_file else 0
                    is_blank = (duration < MIN_DURATION_MINUTES) or (video_file_size < MIN_FILE_SIZE_BYTES)

                    if is_blank:
                        logger.info(
                            f"Recording '{display_name}' marked as blank: "
                            f"duration={duration}min (min={MIN_DURATION_MINUTES}), "
                            f"size={video_file_size} bytes (min={MIN_FILE_SIZE_BYTES})"
                        )

                    # Template matching
                    matched_template = _find_matching_template(display_name, source_id, templates)

                    # Create or update
                    recording, is_new = await recording_repo.create_or_update(
                        user_id=user_id,
                        input_source_id=source_id,
                        display_name=display_name,
                        start_time=start_time,
                        duration=duration,
                        source_type=SourceType.ZOOM,
                        source_key=meeting_id,
                        source_metadata=source_metadata,
                        video_file_size=video_file.get("file_size") if video_file else None,
                        is_mapped=matched_template is not None,
                        template_id=matched_template.id if matched_template else None,
                        blank_record=is_blank,
                    )

                    if is_new:
                        saved_count += 1
                    else:
                        updated_count += 1

                except Exception as e:
                    logger.warning(f"Failed to save recording {meeting.get('id')}: {e}")
                    continue

            logger.info(f"Synced {saved_count + updated_count} recordings from source {source_id} (new={saved_count}, updated={updated_count})")

        except Exception as e:
            logger.error(f"Zoom sync failed for source {source_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
            }

    elif source.source_type == "YANDEX_DISK":
        return {
            "status": "error",
            "error": "Yandex Disk sync not implemented yet",
        }

    elif source.source_type == "LOCAL":
        # LOCAL sources don't need sync
        pass

    else:
        return {
            "status": "error",
            "error": f"Unknown source type: {source.source_type}",
        }

    # Обновляем last_sync_at
    await repo.update_last_sync(source)

    recordings_found = len(meetings) if source.source_type == "ZOOM" else 0
    recordings_saved = saved_count if source.source_type == "ZOOM" else 0
    recordings_updated = updated_count if source.source_type == "ZOOM" else 0

    return {
        "status": "success",
        "recordings_found": recordings_found,
        "recordings_saved": recordings_saved,
        "recordings_updated": recordings_updated,
    }


def _find_matching_template(
    display_name: str,
    source_id: int,
    templates: list
):
    """
    Найти первый подходящий template (first_match strategy).

    Matching rules проверяются в следующем порядке:
    - exact_matches: точное совпадение названия
    - keywords: наличие ключевого слова в названии
    - patterns: regex паттерны
    - source_id: опционально (если указан в matching_rules, проверяется)

    Args:
        display_name: Название записи
        source_id: ID источника записи
        templates: Список активных шаблонов (отсортированы по created_at ASC)

    Returns:
        RecordingTemplateModel | None: Первый matched template или None

    Note: Поле priority НЕ используется (simple first_match).
    Порядок определяется created_at ASC (старые templates проверяются первыми).
    """
    import re

    if not templates:
        return None

    display_name_lower = display_name.lower().strip()

    for template in templates:
        matching_rules = template.matching_rules or {}

        # Check source_id filter first (if specified)
        template_source_ids = matching_rules.get("source_ids", [])
        if template_source_ids and source_id not in template_source_ids:
            continue

        # Check exact matches
        exact_matches = matching_rules.get("exact_matches", [])
        if exact_matches:
            for exact in exact_matches:
                if isinstance(exact, str) and exact.lower() == display_name_lower:
                    logger.debug(
                        f"Recording '{display_name}' matched template '{template.name}' "
                        f"by exact match"
                    )
                    return template

        # Check keywords
        keywords = matching_rules.get("keywords", [])
        if keywords:
            for keyword in keywords:
                if isinstance(keyword, str) and keyword.lower() in display_name_lower:
                    logger.debug(
                        f"Recording '{display_name}' matched template '{template.name}' "
                        f"by keyword '{keyword}'"
                    )
                    return template

        # Check regex patterns
        patterns = matching_rules.get("patterns", [])
        if patterns:
            for pattern in patterns:
                if isinstance(pattern, str):
                    try:
                        if re.search(pattern, display_name, re.IGNORECASE):
                            logger.debug(
                                f"Recording '{display_name}' matched template '{template.name}' "
                                f"by pattern '{pattern}'"
                            )
                            return template
                    except re.error as e:
                        logger.warning(
                            f"Invalid regex pattern '{pattern}' in template '{template.name}': {e}"
                        )

    logger.debug(f"Recording '{display_name}' did not match any template")
    return None


def _check_recording_mapping(display_name: str, templates: list) -> bool:
    """
    Проверяет, соответствует ли запись хотя бы одному шаблону.

    Deprecated: Use _find_matching_template instead.
    Kept for backward compatibility.

    Args:
        display_name: Название записи
        templates: Список активных шаблонов пользователя

    Returns:
        True если найдено совпадение, False иначе
    """
    return _find_matching_template(display_name, source_id=0, templates=templates) is not None


@router.get("", response_model=list[InputSourceResponse])
async def list_sources(
    active_only: bool = False,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение списка источников пользователя."""
    repo = InputSourceRepository(session)

    if active_only:
        sources = await repo.find_active_by_user(current_user.id)
    else:
        sources = await repo.find_by_user(current_user.id)

    return sources


@router.get("/{source_id}", response_model=InputSourceResponse)
async def get_source(
    source_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Получение источника по ID."""
    repo = InputSourceRepository(session)
    source = await repo.find_by_id(source_id, current_user.id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )

    return source


@router.post("", response_model=InputSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    data: InputSourceCreate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Создание нового источника."""
    repo = InputSourceRepository(session)

    source_type = data.platform.value.upper()

    if data.credential_id:
        cred_repo = UserCredentialRepository(session)
        credential = await cred_repo.get_by_id(data.credential_id)
        if not credential or credential.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credential {data.credential_id} not found"
            )

    # Проверка на дубликаты
    duplicate = await repo.find_duplicate(
        user_id=current_user.id,
        name=data.name,
        source_type=source_type,
        credential_id=data.credential_id,
    )

    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Source with name '{data.name}', type '{source_type}' and credential_id {data.credential_id} already exists"
        )

    source = await repo.create(
        user_id=current_user.id,
        name=data.name,
        source_type=source_type,
        credential_id=data.credential_id,
        config=data.config,
        description=data.description,
    )

    await session.commit()
    return source


@router.patch("/{source_id}", response_model=InputSourceResponse)
async def update_source(
    source_id: int,
    data: InputSourceUpdate,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Обновление источника."""
    repo = InputSourceRepository(session)
    source = await repo.find_by_id(source_id, current_user.id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(source, field, value)

    await repo.update(source)
    await session.commit()

    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """Удаление источника."""
    repo = InputSourceRepository(session)
    source = await repo.find_by_id(source_id, current_user.id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )

    await repo.delete(source)
    await session.commit()


@router.post("/{source_id}/sync", response_model=dict)
async def sync_source(
    source_id: int,
    from_date: str = "2024-01-01",
    to_date: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Синхронизация записей из одного источника (async через Celery).

    Args:
        source_id: ID источника
        from_date: Дата начала в формате YYYY-MM-DD
        to_date: Дата окончания в формате YYYY-MM-DD (опционально)

    Returns:
        task_id для отслеживания прогресса через GET /api/v1/tasks/{task_id}
    """
    # Проверяем что source существует и принадлежит пользователю
    repo = InputSourceRepository(session)
    source = await repo.find_by_id(source_id, current_user.id)

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source {source_id} not found"
        )

    if not source.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source is not active"
        )

    # Запускаем Celery task
    from api.tasks.sync_tasks import sync_single_source_task

    task = sync_single_source_task.apply_async(
        kwargs={
            "source_id": source_id,
            "user_id": current_user.id,
            "from_date": from_date,
            "to_date": to_date,
        }
    )

    logger.info(f"Started sync task {task.id} for source {source_id} (user {current_user.id})")

    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"Sync task started for source {source_id}",
        "source_id": source_id,
        "source_name": source.name,
    }


@router.post("/batch-sync", response_model=dict)
async def batch_sync_sources(
    data: BatchSyncRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: UserModel = Depends(get_current_active_user),
):
    """
    Батчевая синхронизация нескольких источников (async через Celery).

    Args:
        data: Запрос с source_ids, from_date, to_date

    Returns:
        task_id для отслеживания прогресса через GET /api/v1/tasks/{task_id}
    """
    # Валидация что все sources существуют и принадлежат пользователю
    repo = InputSourceRepository(session)
    invalid_sources = []
    source_names = []

    for source_id in data.source_ids:
        source = await repo.find_by_id(source_id, current_user.id)
        if not source:
            invalid_sources.append(source_id)
        else:
            source_names.append(source.name)

    if invalid_sources:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sources not found: {invalid_sources}"
        )

    # Запускаем Celery task
    from api.tasks.sync_tasks import batch_sync_sources_task

    task = batch_sync_sources_task.apply_async(
        kwargs={
            "source_ids": data.source_ids,
            "user_id": current_user.id,
            "from_date": data.from_date,
            "to_date": data.to_date,
        }
    )

    logger.info(f"Started batch sync task {task.id} for {len(data.source_ids)} sources (user {current_user.id})")

    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"Batch sync task started for {len(data.source_ids)} sources",
        "source_ids": data.source_ids,
        "source_names": source_names,
    }

