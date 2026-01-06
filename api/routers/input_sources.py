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


def _check_recording_mapping(display_name: str, templates: list) -> bool:
    """
    Проверяет, соответствует ли запись хотя бы одному шаблону.

    Args:
        display_name: Название записи
        templates: Список активных шаблонов пользователя

    Returns:
        True если найдено совпадение, False иначе
    """
    if not templates:
        return False

    display_name_lower = display_name.lower().strip()

    for template in templates:
        # Проверяем matching_rules шаблона
        matching_rules = template.matching_rules or {}

        # Проверка по ключевым словам (keywords)
        keywords = matching_rules.get("keywords", [])
        if keywords:
            for keyword in keywords:
                if isinstance(keyword, str) and keyword.lower() in display_name_lower:
                    logger.debug(f"Recording '{display_name}' matched template '{template.name}' by keyword '{keyword}'")
                    return True

        # Проверка по паттернам (patterns)
        patterns = matching_rules.get("patterns", [])
        if patterns:
            import re
            for pattern in patterns:
                if isinstance(pattern, str):
                    try:
                        if re.search(pattern, display_name, re.IGNORECASE):
                            logger.debug(f"Recording '{display_name}' matched template '{template.name}' by pattern '{pattern}'")
                            return True
                    except re.error as e:
                        logger.warning(f"Invalid regex pattern '{pattern}' in template '{template.name}': {e}")

        # Проверка по точному совпадению (exact_match)
        exact_matches = matching_rules.get("exact_matches", [])
        if exact_matches:
            for exact in exact_matches:
                if isinstance(exact, str) and exact.lower() == display_name_lower:
                    logger.debug(f"Recording '{display_name}' matched template '{template.name}' by exact match")
                    return True

    logger.debug(f"Recording '{display_name}' did not match any template")
    return False


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
    Синхронизация записей из источника.

    Args:
        source_id: ID источника
        from_date: Дата начала в формате YYYY-MM-DD
        to_date: Дата окончания в формате YYYY-MM-DD (опционально)
        session: Database session
        current_user: Текущий пользователь

    Returns:
        Статус синхронизации
    """
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

    if not source.credential_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source has no credential configured"
        )

    # Получаем credentials для источника
    cred_repo = UserCredentialRepository(session)
    credential = await cred_repo.get_by_id(source.credential_id)

    if not credential:
        logger.error(f"Failed to get credentials for source {source_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credentials {source.credential_id} not found"
        )

    from api.auth.encryption import get_encryption
    encryption = get_encryption()
    credentials = encryption.decrypt_credentials(credential.encrypted_data)

    # Синхронизация в зависимости от типа источника
    meetings = []
    saved_count = 0

    if source.source_type == "ZOOM":
        try:
            # Создаем ZoomConfig из credentials
            zoom_config = ZoomConfig(
                account=credentials.get("account", ""),
                account_id=credentials["account_id"],
                client_id=credentials["client_id"],
                client_secret=credentials["client_secret"],
            )

            # Создаем Zoom API клиент
            zoom_api = ZoomAPI(zoom_config)

            # Получаем записи
            recordings_data = await zoom_api.get_recordings(
                from_date=from_date,
                to_date=to_date,
            )

            meetings = recordings_data.get("meetings", [])

            logger.info(f"Found {len(meetings)} recordings from Zoom source {source_id}")

            # Получаем активные шаблоны пользователя для проверки маппинга
            template_repo = RecordingTemplateRepository(session)
            templates = await template_repo.find_active_by_user(current_user.id)

            # Сохраняем recordings в БД
            recording_repo = RecordingAsyncRepository(session)
            saved_count = 0
            updated_count = 0

            for meeting in meetings:
                try:
                    # Парсим данные из Zoom
                    meeting_id = meeting.get("uuid", meeting.get("id", ""))
                    display_name = meeting.get("topic", "Untitled")
                    start_time_str = meeting.get("start_time", "")
                    duration = meeting.get("duration", 0)

                    # Парсим start_time
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
                        # Берем первый MP4 файл
                        for file in recording_files:
                            if file.get("file_type") == "MP4":
                                video_file = file
                                break

                    # Получаем детальную информацию с download_access_token
                    download_access_token = None
                    meeting_details = None
                    try:
                        meeting_details = await zoom_api.get_recording_details(meeting_id, include_download_token=True)
                        download_access_token = meeting_details.get("download_access_token")
                        logger.info(f"Got download_access_token for meeting {meeting_id}: {bool(download_access_token)}")
                    except Exception as e:
                        logger.warning(f"Failed to get download_access_token for meeting {meeting_id}: {e}")

                    # Собираем метаданные (сохраняем все важные поля из Zoom API)
                    source_metadata = {
                        # Основные идентификаторы
                        "meeting_id": meeting_id,
                        "account": credentials.get("account", ""),
                        "account_id": meeting.get("account_id"),
                        "host_id": meeting.get("host_id"),
                        "host_email": meeting.get("host_email"),

                        # Информация о записи
                        "share_url": meeting.get("share_url"),  # Ссылка на просмотр в Zoom
                        "recording_play_passcode": meeting.get("recording_play_passcode"),
                        "password": meeting.get("password"),
                        "timezone": meeting.get("timezone"),
                        "total_size": meeting.get("total_size"),
                        "recording_count": meeting.get("recording_count"),

                        # Информация о видео файле
                        "download_url": video_file.get("download_url") if video_file else None,
                        "play_url": video_file.get("play_url") if video_file else None,  # Ссылка для проигрывания
                        "download_access_token": download_access_token,
                        "video_file_size": video_file.get("file_size") if video_file else None,
                        "video_file_type": video_file.get("file_type") if video_file else None,
                        "recording_type": video_file.get("recording_type") if video_file else None,

                        # Информация об удалении
                        "delete_time": meeting.get("delete_time"),  # Дата удаления (если в корзине)
                        "auto_delete_date": meeting.get("auto_delete_date"),  # Дата автоматического удаления

                        # Полные данные от API (для возможности доступа к любым полям)
                        "zoom_api_meeting": meeting,  # Полный ответ от get_recordings
                        "zoom_api_details": meeting_details if meeting_details else {},  # Детали с download_token
                    }

                    # Проверяем маппинг с шаблонами
                    is_mapped = _check_recording_mapping(display_name, templates)

                    # Создаем или обновляем запись (upsert)
                    recording, is_new = await recording_repo.create_or_update(
                        user_id=current_user.id,
                        input_source_id=source_id,
                        display_name=display_name,
                        start_time=start_time,
                        duration=duration,
                        source_type=SourceType.ZOOM,
                        source_key=meeting_id,
                        source_metadata=source_metadata,
                        video_file_size=video_file.get("file_size") if video_file else None,
                        is_mapped=is_mapped,
                    )

                    if is_new:
                        saved_count += 1
                    else:
                        updated_count += 1

                except Exception as e:
                    logger.warning(f"Failed to save recording {meeting.get('id')}: {e}")
                    continue

            await session.commit()

            logger.info(f"Synced {saved_count + updated_count} recordings from Zoom source {source_id} (new={saved_count}, updated={updated_count})")

        except Exception as e:
            logger.error(f"Zoom sync failed for source {source_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Sync failed: {str(e)}"
            )

    elif source.source_type == "YANDEX_DISK":
        # TODO: Implement Yandex Disk sync
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Yandex Disk sync not implemented yet"
        )

    elif source.source_type == "LOCAL":
        # LOCAL sources don't need sync
        pass

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source type: {source.source_type}"
        )

    # Обновляем время последней синхронизации
    await repo.update_last_sync(source)
    await session.commit()

    recordings_found = len(meetings) if source.source_type == "ZOOM" else 0
    recordings_saved = saved_count if source.source_type == "ZOOM" else 0
    recordings_updated = updated_count if source.source_type == "ZOOM" else 0

    return {
        "message": "Sync completed",
        "source_id": source_id,
        "source_type": source.source_type,
        "recordings_found": recordings_found,
        "recordings_saved": recordings_saved,
        "recordings_updated": recordings_updated,
    }

