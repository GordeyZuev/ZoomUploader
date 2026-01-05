"""API endpoints для recordings с multi-tenancy support."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from api.core.context import ServiceContext
from api.core.dependencies import get_service_context
from api.repositories.recording_repos import RecordingAsyncRepository
from logger import get_logger
from models import ProcessingStatus

router = APIRouter(prefix="/api/v1/recordings", tags=["Recordings"])
logger = get_logger()


# ============================================================================
# Pydantic Models
# ============================================================================


class RecordingResponse(BaseModel):
    """Response модель для recording."""

    id: int
    meeting_id: str
    display_name: str
    start_time: str
    duration: int | None = None
    status: str
    local_video_path: str | None = None
    processed_video_path: str | None = None
    transcription_dir: str | None = None
    main_topics: list[str] | None = None
    failed: bool = False
    failed_reason: str | None = None

    class Config:
        from_attributes = True


class RecordingListResponse(BaseModel):
    """Response для списка записей."""

    total: int
    recordings: list[RecordingResponse]
    page: int
    per_page: int


class ProcessVideoRequest(BaseModel):
    """Request для обработки видео."""

    silence_threshold: float = -40.0
    min_silence_duration: float = 2.0
    padding_before: float = 5.0
    padding_after: float = 5.0


class FullPipelineRequest(BaseModel):
    """Request для полного пайплайна."""

    download: bool = True
    process: bool = True
    transcribe: bool = True
    upload: bool = False
    platforms: list[str] = []
    preset_ids: dict[str, int] | None = None
    granularity: str = "long"
    process_config: ProcessVideoRequest = ProcessVideoRequest()


# ============================================================================
# CRUD Endpoints
# ============================================================================


@router.get("", response_model=RecordingListResponse)
async def list_recordings(
    status_filter: str | None = Query(None, description="Фильтр по статусу"),
    failed: bool | None = Query(None, description="Только failed записи"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Получить список записей пользователя.

    Args:
        status_filter: Фильтр по статусу (INITIALIZED, DOWNLOADED, PROCESSED, etc.)
        failed: Только failed записи
        page: Номер страницы
        per_page: Количество записей на страницу
        ctx: Service context

    Returns:
        Список записей
    """
    recording_repo = RecordingAsyncRepository(ctx.session)

    # Получаем все записи пользователя
    recordings = await recording_repo.list_by_user(ctx.user_id)

    # Применяем фильтры
    if status_filter:
        recordings = [r for r in recordings if r.status.value == status_filter]

    if failed is not None:
        recordings = [r for r in recordings if r.failed == failed]

    # Пагинация
    total = len(recordings)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_recordings = recordings[start:end]

    return RecordingListResponse(
        total=total,
        recordings=[
            RecordingResponse(
                id=r.id,
                meeting_id=r.source.source_key if r.source else None,
                display_name=r.display_name,
                start_time=r.start_time.isoformat(),
                duration=r.duration,
                status=r.status.value,
                local_video_path=r.local_video_path,
                processed_video_path=r.processed_video_path,
                transcription_dir=r.transcription_dir,
                main_topics=r.main_topics,
                failed=r.failed,
                failed_reason=r.failed_reason,
            )
            for r in paginated_recordings
        ],
        page=page,
        per_page=per_page,
    )


@router.get("/{recording_id}", response_model=RecordingResponse)
async def get_recording(
    recording_id: int,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Получить одну запись по ID.

    Args:
        recording_id: ID записи
        ctx: Service context

    Returns:
        Recording
    """
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    return RecordingResponse(
        id=recording.id,
        meeting_id=recording.source.source_key if recording.source else None,
        display_name=recording.display_name,
        start_time=recording.start_time.isoformat(),
        duration=recording.duration,
        status=recording.status.value,
        local_video_path=recording.local_video_path,
        processed_video_path=recording.processed_video_path,
        transcription_dir=recording.transcription_dir,
        main_topics=recording.main_topics,
        failed=recording.failed,
        failed_reason=recording.failed_reason,
    )


@router.post("")
async def add_local_recording(
    file: UploadFile = File(...),
    display_name: str = Query(..., description="Название записи"),
    meeting_id: str | None = Query(None, description="ID встречи (опционально)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Добавить локальное видео.

    Args:
        file: Видео файл
        display_name: Название записи
        meeting_id: ID встречи (опционально)
        ctx: Service context

    Returns:
        Созданная запись
    """
    # Создаем директорию для пользователя
    user_dir = Path(f"media/user_{ctx.user_id}/video/unprocessed")
    user_dir.mkdir(parents=True, exist_ok=True)

    # Сохраняем файл
    filename = file.filename or "uploaded_video.mp4"
    file_path = user_dir / filename

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        logger.info(f"Saved uploaded file: {file_path} ({len(content)} bytes)")

        # Создаем запись в БД
        recording_repo = RecordingAsyncRepository(ctx.session)

        from datetime import datetime

        from database.models import RecordingModel, SourceMetadataModel
        from models.recording import SourceType

        recording = RecordingModel(
            user_id=ctx.user_id,
            display_name=display_name,
            start_time=datetime.now(),
            duration=0,
            status=ProcessingStatus.DOWNLOADED,
            local_video_path=str(file_path),
        )

        created_recording = await recording_repo.create(recording)

        # Создаем source metadata если указан meeting_id
        if meeting_id:
            source_meta = SourceMetadataModel(
                recording_id=created_recording.id,
                user_id=ctx.user_id,
                source_type=SourceType.LOCAL,
                source_key=meeting_id,
                meta={"uploaded_via_api": True},
            )
            ctx.session.add(source_meta)

        await ctx.session.commit()

        return {
            "success": True,
            "recording_id": created_recording.id,
            "display_name": created_recording.display_name,
            "local_video_path": str(file_path),
        }

    except Exception as e:
        logger.error(f"Failed to upload file: {e}", exc_info=True)
        if file_path.exists():
            file_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}",
        )


# ============================================================================
# Processing Endpoints
# ============================================================================


@router.post("/{recording_id}/download")
async def download_recording(
    recording_id: int,
    force: bool = Query(False, description="Пересохранить если уже скачано"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Скачать запись из Zoom (асинхронная задача).

    Args:
        recording_id: ID записи
        force: Пересохранить если уже скачано
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения.
    """
    from api.tasks.processing import download_recording_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Проверяем, что у нас есть download_url в source metadata
    download_url = None
    if recording.source and recording.source.meta:
        download_url = recording.source.meta.get("download_url")

    if not download_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No download URL available for this recording. Please sync from Zoom first.",
        )

    # Проверяем, что не скачано уже
    if not force and recording.status == ProcessingStatus.DOWNLOADED and recording.local_video_path:
        if Path(recording.local_video_path).exists():
            return {
                "success": True,
                "message": "Recording already downloaded",
                "recording_id": recording_id,
                "local_video_path": recording.local_video_path,
                "task_id": None,
            }

    # Запускаем асинхронную задачу
    task = download_recording_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        force=force,
    )

    logger.info(f"Download task {task.id} created for recording {recording_id}, user {ctx.user_id}")

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Download task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.post("/{recording_id}/process")
async def process_recording(
    recording_id: int,
    config: ProcessVideoRequest = ProcessVideoRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Обработать видео (FFmpeg - удаление тишины) - асинхронная задача.

    Args:
        recording_id: ID записи
        config: Конфигурация обработки
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения.
    """
    from api.tasks.processing import process_video_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Проверяем наличие исходного видео
    if not recording.local_video_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No video file available. Please download the recording first.",
        )

    if not Path(recording.local_video_path).exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video file not found at path: {recording.local_video_path}",
        )

    # Запускаем асинхронную задачу
    task = process_video_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        silence_threshold=config.silence_threshold,
        min_silence_duration=config.min_silence_duration,
        padding_before=config.padding_before,
        padding_after=config.padding_after,
    )

    logger.info(f"Process task {task.id} created for recording {recording_id}, user {ctx.user_id}")

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Processing task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.post("/batch-process")
async def batch_process_recordings(
    recording_ids: list[int] = Query(..., description="Список ID записей"),
    config: FullPipelineRequest = FullPipelineRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Пакетная обработка нескольких записей (асинхронные задачи).

    Args:
        recording_ids: Список ID записей
        config: Конфигурация пайплайна
        ctx: Service context

    Returns:
        Список task_id для каждой записи

    Note:
        Каждая запись обрабатывается в отдельной задаче.
        Используйте GET /api/v1/tasks/{task_id} для проверки статуса каждой задачи.
    """
    from api.tasks.processing import full_pipeline_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            # Проверяем существование записи
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

            if not recording:
                tasks.append({
                    "recording_id": recording_id,
                    "status": "error",
                    "error": "Recording not found or no access",
                    "task_id": None,
                })
                continue

            # Запускаем задачу для этой записи
            task = full_pipeline_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                download=config.download,
                process=config.process,
                transcribe=config.transcribe,
                upload=config.upload,
                platforms=config.platforms,
                preset_ids=config.preset_ids,
                granularity=config.granularity,
                process_config={
                    "silence_threshold": config.process_config.silence_threshold,
                    "min_silence_duration": config.process_config.min_silence_duration,
                    "padding_before": config.process_config.padding_before,
                    "padding_after": config.process_config.padding_after,
                },
            )

            tasks.append({
                "recording_id": recording_id,
                "status": "queued",
                "task_id": task.id,
                "check_status_url": f"/api/v1/tasks/{task.id}",
            })

            logger.info(f"Batch task {task.id} created for recording {recording_id}, user {ctx.user_id}")

        except Exception as e:
            logger.error(f"Failed to create task for recording {recording_id}: {e}")
            tasks.append({
                "recording_id": recording_id,
                "status": "error",
                "error": str(e),
                "task_id": None,
            })

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    error_count = len([t for t in tasks if t["status"] == "error"])

    return {
        "total": len(recording_ids),
        "queued": queued_count,
        "errors": error_count,
        "tasks": tasks,
    }


@router.post("/{recording_id}/full-pipeline")
async def full_pipeline_processing(
    recording_id: int,
    config: FullPipelineRequest = FullPipelineRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Полный пайплайн обработки (асинхронная задача): download → process → transcribe → upload.

    Args:
        recording_id: ID записи
        config: Конфигурация пайплайна
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция, выполняющая все шаги последовательно.
        Используйте GET /api/v1/tasks/{task_id} для проверки прогресса.
    """
    from api.tasks.processing import full_pipeline_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Запускаем полный пайплайн как одну задачу
    task = full_pipeline_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        download=config.download,
        process=config.process,
        transcribe=config.transcribe,
        upload=config.upload,
        platforms=config.platforms,
        preset_ids=config.preset_ids,
        granularity=config.granularity,
        process_config={
            "silence_threshold": config.process_config.silence_threshold,
            "min_silence_duration": config.process_config.min_silence_duration,
            "padding_before": config.process_config.padding_before,
            "padding_after": config.process_config.padding_after,
        },
    )

    logger.info(f"Full pipeline task {task.id} created for recording {recording_id}, user {ctx.user_id}")

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Full pipeline task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
        "steps": {
            "download": config.download,
            "process": config.process,
            "transcribe": config.transcribe,
            "upload": config.upload and len(config.platforms) > 0,
        },
    }


@router.post("/{recording_id}/transcribe")
async def transcribe_recording(
    recording_id: int,
    granularity: str = "long",
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Транскрибировать запись (асинхронная задача) с использованием user credentials.

    Args:
        recording_id: ID записи
        granularity: Режим извлечения тем ("short" | "long")
        ctx: Service context с user_id и session

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения и получения результатов.
    """
    from api.tasks.processing import transcribe_recording_task

    # Получаем запись из БД
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access"
        )

    # Проверяем наличие файла для обработки
    if not recording.processed_video_path and not recording.local_video_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No video file available for transcription. Please download the recording first."
        )

    audio_path = recording.processed_video_path or recording.local_video_path

    # Проверяем существование файла
    if not Path(audio_path).exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video file not found at path: {audio_path}"
        )

    # Запускаем асинхронную задачу
    task = transcribe_recording_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        granularity=granularity,
    )

    logger.info(f"Transcription task {task.id} created for recording {recording_id}, user {ctx.user_id}")

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Transcription task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.post("/{recording_id}/upload/{platform}")
async def upload_recording(
    recording_id: int,
    platform: str,
    preset_id: int | None = None,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Загрузить запись на платформу (асинхронная задача) с использованием user credentials.

    Args:
        recording_id: ID записи
        platform: Платформа (youtube, vk)
        preset_id: ID output preset (опционально)
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения и получения результатов.
    """
    from api.tasks.upload import upload_recording_to_platform

    # Получаем запись из БД
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access"
        )

    # Проверяем наличие обработанного видео
    if not recording.processed_video_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No processed video available. Please process the recording first."
        )

    video_path = recording.processed_video_path

    # Проверяем существование файла
    if not Path(video_path).exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Processed video file not found at path: {video_path}"
        )

    # Запускаем асинхронную задачу
    task = upload_recording_to_platform.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        platform=platform,
        preset_id=preset_id,
    )

    logger.info(
        f"Upload task {task.id} created for recording {recording_id} to {platform}, "
        f"user {ctx.user_id}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "platform": platform,
        "status": "queued",
        "message": f"Upload task to {platform} has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }



