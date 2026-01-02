"""API endpoints для работы с источниками данных."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_active_user
from api.dependencies import get_db_session
from api.repositories.recording_repos import RecordingAsyncRepository
from api.repositories.template_repos import InputSourceRepository
from api.schemas.template import (
    InputSourceCreate,
    InputSourceResponse,
    InputSourceUpdate,
)
from api.services.credential_service import CredentialService
from api.zoom_api import ZoomAPI
from config.settings import ZoomConfig
from database.auth_models import UserModel
from logger import get_logger
from models.recording import SourceType

router = APIRouter(prefix="/sources", tags=["input-sources"])
logger = get_logger()


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
    source = await repo.create(
        user_id=current_user.id,
        name=data.name,
        source_type=data.source_type,
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
    cred_service = CredentialService(session)

    try:
        credentials = await cred_service.get_credentials_by_id(source.credential_id)
    except ValueError as e:
        logger.error(f"Failed to get credentials for source {source_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credentials not found: {str(e)}"
        )

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

            # Сохраняем recordings в БД
            recording_repo = RecordingAsyncRepository(session)
            saved_count = 0

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

                    # Собираем метаданные
                    source_metadata = {
                        "meeting_id": meeting_id,
                        "account": credentials.get("account", ""),
                        "video_file_download_url": video_file.get("download_url") if video_file else None,
                        "video_file_size": video_file.get("file_size") if video_file else None,
                        "password": meeting.get("password"),
                        "recording_play_passcode": meeting.get("recording_play_passcode"),
                    }

                    # Создаем запись
                    await recording_repo.create(
                        user_id=current_user.id,
                        input_source_id=source_id,
                        display_name=display_name,
                        start_time=start_time,
                        duration=duration,
                        source_type=SourceType.ZOOM,
                        source_key=meeting_id,
                        source_metadata=source_metadata,
                        video_file_size=video_file.get("file_size") if video_file else None,
                    )

                    saved_count += 1

                except Exception as e:
                    logger.warning(f"Failed to save recording {meeting.get('id')}: {e}")
                    continue

            await session.commit()

            logger.info(f"Saved {saved_count}/{len(meetings)} recordings from Zoom source {source_id}")

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

    return {
        "message": "Sync completed",
        "source_id": source_id,
        "source_type": source.source_type,
        "recordings_found": recordings_found,
        "recordings_saved": recordings_saved,
    }

