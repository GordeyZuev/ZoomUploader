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
        # Сохраняем файл по частям для больших файлов
        total_size = 0
        with open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # Читаем по 1MB
                f.write(chunk)
                total_size += len(chunk)

        logger.info(f"Saved uploaded file: {file_path} ({total_size} bytes, filename: {filename})")

        # Проверяем, что файл действительно сохранился
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save uploaded file",
            )

        actual_size = file_path.stat().st_size
        if actual_size != total_size:
            logger.warning(f"File size mismatch: expected {total_size}, got {actual_size}")

        logger.info(f"File verified: {file_path} exists with size {actual_size} bytes")

        # Создаем запись в БД
        recording_repo = RecordingAsyncRepository(ctx.session)

        from datetime import datetime

        from models.recording import SourceType

        # Используем meeting_id или генерируем уникальный ключ
        source_key = meeting_id or f"local_{ctx.user_id}_{datetime.now().timestamp()}"

        created_recording = await recording_repo.create(
            user_id=ctx.user_id,
            input_source_id=None,
            display_name=display_name,
            start_time=datetime.now(),
            duration=0,
            source_type=SourceType.LOCAL_FILE,
            source_key=source_key,
            source_metadata={"uploaded_via_api": True, "original_filename": filename},
            status=ProcessingStatus.DOWNLOADED,
            local_video_path=str(file_path),
            video_file_size=actual_size,
        )

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
    allow_skipped: bool | None = Query(None, description="Разрешить загрузку SKIPPED записей (default: из конфига)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Скачать запись из Zoom (асинхронная задача).

    Args:
        recording_id: ID записи
        force: Пересохранить если уже скачано
        allow_skipped: Разрешить загрузку SKIPPED записей (если None - берется из конфига)
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения.

        По умолчанию SKIPPED записи не загружаются. Для их загрузки нужно:
        - Явно передать allow_skipped=true в query параметре, ИЛИ
        - Установить allow_skipped=true в user_config.processing
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_download
    from api.tasks.processing import download_recording_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Получаем флаг allow_skipped из конфига/параметра
    allow_skipped_resolved = await get_allow_skipped_flag(
        ctx.session, ctx.user_id, explicit_value=allow_skipped
    )

    # Проверяем, можно ли загрузить (учитывая SKIPPED статус)
    if not should_allow_download(recording, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Download not allowed for recording with status {recording.status.value}. "
            f"SKIPPED recordings require allow_skipped=true.",
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
    allow_skipped: bool | None = Query(None, description="Разрешить обработку SKIPPED записей (default: из конфига)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Обработать видео (FFmpeg - удаление тишины) - асинхронная задача.

    Args:
        recording_id: ID записи
        config: Конфигурация обработки
        allow_skipped: Разрешить обработку SKIPPED записей (если None - берется из конфига)
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения.

        По умолчанию SKIPPED записи не обрабатываются. Для их обработки нужно:
        - Явно передать allow_skipped=true в query параметре, ИЛИ
        - Установить allow_skipped=true в user_config.processing
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_processing
    from api.tasks.processing import process_video_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Получаем флаг allow_skipped из конфига/параметра
    allow_skipped_resolved = await get_allow_skipped_flag(
        ctx.session, ctx.user_id, explicit_value=allow_skipped
    )

    # Проверяем, можно ли обработать (учитывая SKIPPED статус)
    if not should_allow_processing(recording, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Processing not allowed for recording with status {recording.status.value}. "
            f"SKIPPED recordings require allow_skipped=true.",
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
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Транскрибировать запись (асинхронная задача) с использованием АДМИНСКИХ кредов.

    ⚠️ ВАЖНО: Создает только master.json (words, segments).
    Для извлечения тем используйте отдельный endpoint /topics.

    Args:
        recording_id: ID записи
        ctx: Service context с user_id и session

    Returns:
        Task ID для проверки статуса

    Note:
        Использует АДМИНСКИЕ креды для транскрибации через Fireworks API.
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения и получения результатов.
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_transcription
    from api.tasks.processing import transcribe_recording_task

    # Получаем запись из БД
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access"
        )

    # Получаем флаг allow_skipped из конфига (для транскрипции можно добавить query param если нужно)
    allow_skipped_resolved = await get_allow_skipped_flag(ctx.session, ctx.user_id)

    # Проверяем, можно ли запустить транскрипцию (используем FSM логику)
    if not should_allow_transcription(recording, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transcription cannot be started. Current status: {recording.status.value}. "
            f"Transcription is already completed or in progress. "
            f"SKIPPED recordings require allow_skipped=true in config."
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
    allow_skipped: bool | None = Query(None, description="Разрешить загрузку SKIPPED записей (default: из конфига)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Загрузить запись на платформу (асинхронная задача) с использованием user credentials.

    Args:
        recording_id: ID записи
        platform: Платформа (youtube, vk)
        preset_id: ID output preset (опционально)
        allow_skipped: Разрешить загрузку SKIPPED записей (если None - берется из конфига)
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения и получения результатов.

        По умолчанию SKIPPED записи не загружаются. Для их загрузки нужно:
        - Явно передать allow_skipped=true в query параметре, ИЛИ
        - Установить allow_skipped=true в user_config.processing, ИЛИ
        - Установить allow_skipped=true в template.output_config
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_upload
    from api.tasks.upload import upload_recording_to_platform
    from models.recording import TargetType

    # Получаем запись из БД
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access"
        )

    # Получаем флаг allow_skipped из конфига/параметра
    allow_skipped_resolved = await get_allow_skipped_flag(
        ctx.session, ctx.user_id, explicit_value=allow_skipped
    )

    # Проверяем, можно ли загрузить на эту платформу (используем FSM логику)
    try:
        target_type_enum = TargetType[platform.upper()]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform: {platform}. Supported: youtube, vk, etc."
        )

    if not should_allow_upload(recording, target_type_enum.value, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload to {platform} cannot be started. Current status: {recording.status.value}. "
            f"Either upload is already completed/in progress, or recording is not ready for upload. "
            f"SKIPPED recordings require allow_skipped=true."
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


# ============================================================================
# NEW: Separate Transcription Pipeline Endpoints
# ============================================================================


@router.post("/{recording_id}/topics")
async def extract_topics(
    recording_id: int,
    granularity: str = Query("long", description="Режим: 'short' или 'long'"),
    version_id: str | None = Query(None, description="ID версии (опционально)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Извлечь темы из существующей транскрибации (асинхронная задача).

    ⚠️ ВАЖНО: Требует наличие транскрибации. Запустите /transcribe сначала.
    ✨ Можно запускать многократно с разными настройками для создания разных версий.

    Args:
        recording_id: ID записи
        granularity: Режим извлечения ('short' - крупные темы | 'long' - детальные)
        version_id: ID версии (если не указан, генерируется автоматически)
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Модель для извлечения тем выбирается автоматически (с ретраями и фоллбэками).
        Использует АДМИНСКИЕ креды для извлечения тем.
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения.
    """
    from api.tasks.processing import extract_topics_task

    # Получаем запись из БД
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Проверяем наличие транскрибации
    from transcription_module.manager import get_transcription_manager

    transcription_manager = get_transcription_manager()
    if not transcription_manager.has_master(recording_id, user_id=ctx.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcription found. Please run /transcribe first.",
        )

    # Запускаем асинхронную задачу
    task = extract_topics_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        granularity=granularity,
        version_id=version_id,
    )

    logger.info(
        f"Extract topics task {task.id} created for recording {recording_id}, "
        f"user {ctx.user_id}, granularity={granularity}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Topic extraction task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.post("/{recording_id}/subtitles")
async def generate_subtitles(
    recording_id: int,
    formats: list[str] = Query(["srt", "vtt"], description="Форматы: 'srt', 'vtt'"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Генерировать субтитры из транскрибации (асинхронная задача).

    ⚠️ ВАЖНО: Требует наличие транскрибации. Запустите /transcribe сначала.

    Args:
        recording_id: ID записи
        formats: Список форматов субтитров ['srt', 'vtt']
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Note:
        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения.
    """
    from api.tasks.processing import generate_subtitles_task

    # Получаем запись из БД
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Проверяем наличие транскрибации
    from transcription_module.manager import get_transcription_manager

    transcription_manager = get_transcription_manager()
    if not transcription_manager.has_master(recording_id, user_id=ctx.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcription found. Please run /transcribe first.",
        )

    # Запускаем асинхронную задачу
    task = generate_subtitles_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        formats=formats,
    )

    logger.info(
        f"Generate subtitles task {task.id} created for recording {recording_id}, "
        f"user {ctx.user_id}, formats={formats}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Subtitle generation task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.get("/{recording_id}/details")
async def get_recording_details(
    recording_id: int,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Получить детальную информацию о записи.

    Включает:
    - Основная информация о записи
    - Видео файлы (оригинал, обработанный)
    - Аудио файлы
    - Транскрибация (статистика, файлы)
    - Топики (все версии)
    - Субтитры
    - Thumbnail
    - Этапы обработки
    - Загрузка на платформы

    Args:
        recording_id: ID записи
        ctx: Service context

    Returns:
        Детальная информация о записи
    """
    from transcription_module.manager import get_transcription_manager

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    transcription_manager = get_transcription_manager()

    # Формируем ответ
    response = {
        "id": recording.id,
        "display_name": recording.display_name,
        "status": recording.status.value,
        "start_time": recording.start_time.isoformat(),
        "duration": recording.duration,
    }

    # Видео файлы
    videos = {}
    if recording.local_video_path:
        path = Path(recording.local_video_path)
        videos["original"] = {
            "path": str(path),
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else None,
            "exists": path.exists(),
        }
    if recording.processed_video_path:
        path = Path(recording.processed_video_path)
        videos["processed"] = {
            "path": str(path),
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else None,
            "exists": path.exists(),
        }
    response["videos"] = videos

    # Аудио файлы
    audio_info = {}
    if recording.processed_audio_dir:
        audio_dir = Path(recording.processed_audio_dir)
        if audio_dir.exists():
            # Найти первый аудио файл в директории
            audio_files = []
            for ext in ("*.mp3", "*.wav", "*.m4a"):
                audio_files.extend(sorted(audio_dir.glob(ext)))

            if audio_files:
                primary_audio = audio_files[0]
                audio_info = {
                    "path": str(primary_audio),
                    "size_mb": round(primary_audio.stat().st_size / (1024 * 1024), 2),
                    "exists": True,
                }
            else:
                audio_info = {
                    "path": str(audio_dir),
                    "exists": True,
                    "size_mb": None,
                }
        else:
            audio_info = {
                "path": str(audio_dir),
                "exists": False,
                "size_mb": None,
            }

    if audio_info:
        response["audio"] = audio_info

    # Транскрибация (скрываем _metadata и модель от пользователя)
    transcription_data = None
    if transcription_manager.has_master(recording_id, user_id=ctx.user_id):
        try:
            master = transcription_manager.load_master(recording_id, user_id=ctx.user_id)
            transcription_data = {
                "exists": True,
                "created_at": master.get("created_at"),
                "language": master.get("language"),
                # Не показываем модель пользователю (есть в _metadata для админа)
                "stats": master.get("stats"),
                "files": {
                    "master": str(transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "master.json"),
                    "segments_txt": str(transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "cache" / "segments.txt"),
                    "words_txt": str(transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "cache" / "words.txt"),
                },
            }
        except Exception as e:
            logger.warning(f"Failed to load transcription for recording {recording_id}: {e}")
            transcription_data = {"exists": False}
    else:
        transcription_data = {"exists": False}

    response["transcription"] = transcription_data

    # Топики (все версии) - скрываем _metadata от пользователя
    topics_data = None
    if transcription_manager.has_topics(recording_id, user_id=ctx.user_id):
        try:
            topics_file = transcription_manager.load_topics(recording_id, user_id=ctx.user_id)

            # Очищаем версии от административных метаданных
            versions_clean = []
            for version in topics_file.get("versions", []):
                version_clean = {k: v for k, v in version.items() if k != "_metadata"}
                versions_clean.append(version_clean)

            topics_data = {
                "exists": True,
                "active_version": topics_file.get("active_version"),
                "versions": versions_clean,
            }
        except Exception as e:
            logger.warning(f"Failed to load topics for recording {recording_id}: {e}")
            topics_data = {"exists": False}
    else:
        topics_data = {"exists": False}

    response["topics"] = topics_data

    # Субтитры
    subtitles = {}
    cache_dir = transcription_manager.get_dir(recording_id) / "cache"
    for fmt in ["srt", "vtt"]:
        subtitle_path = cache_dir / f"subtitles.{fmt}"
        subtitles[fmt] = {
            "path": str(subtitle_path) if subtitle_path.exists() else None,
            "exists": subtitle_path.exists(),
            "size_kb": round(subtitle_path.stat().st_size / 1024, 2) if subtitle_path.exists() else None,
        }
    response["subtitles"] = subtitles

    # Этапы обработки
    if hasattr(recording, "processing_stages") and recording.processing_stages:
        response["processing_stages"] = [
            {
                "type": stage.stage_type.value if hasattr(stage.stage_type, "value") else str(stage.stage_type),
                "status": stage.status.value if hasattr(stage.status, "value") else str(stage.status),
                "created_at": stage.created_at.isoformat() if stage.created_at else None,
                "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
                "meta": stage.stage_meta,
            }
            for stage in recording.processing_stages
        ]

    # Загрузка на платформы
    uploads = {}
    if hasattr(recording, "output_targets") and recording.output_targets:
        for target in recording.output_targets:
            platform = target.target_type.value if hasattr(target.target_type, "value") else str(target.target_type)
            uploads[platform] = {
                "status": target.status.value if hasattr(target.status, "value") else str(target.status),
                "url": target.get_link() if hasattr(target, "get_link") else None,
                "uploaded_at": target.uploaded_at.isoformat() if hasattr(target, "uploaded_at") and target.uploaded_at else None,
            }
    response["uploads"] = uploads

    return response


@router.post("/batch/transcribe")
async def batch_transcribe_recordings(
    recording_ids: list[int] = Query(..., description="Список ID записей"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Батчевая транскрибация нескольких записей (асинхронные задачи).

    ⚠️ ВАЖНО: Использует АДМИНСКИЕ креды для транскрибации.
    Создает только master.json для каждой записи.
    Для извлечения тем используйте /topics после транскрибации.

    Args:
        recording_ids: Список ID записей для транскрибации
        ctx: Service context

    Returns:
        Список task_id для каждой записи

    Note:
        Каждая запись транскрибируется в отдельной задаче.
        Используйте GET /api/v1/tasks/{task_id} для проверки статуса каждой задачи.
    """
    from api.tasks.processing import transcribe_recording_task

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

            # Проверяем наличие файла
            if not recording.processed_video_path and not recording.local_video_path:
                tasks.append({
                    "recording_id": recording_id,
                    "status": "error",
                    "error": "No video file available",
                    "task_id": None,
                })
                continue

            # Запускаем задачу для этой записи
            task = transcribe_recording_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
            )

            tasks.append({
                "recording_id": recording_id,
                "status": "queued",
                "task_id": task.id,
                "check_status_url": f"/api/v1/tasks/{task.id}",
            })

            logger.info(f"Batch transcribe task {task.id} created for recording {recording_id}, user {ctx.user_id}")

        except Exception as e:
            logger.error(f"Failed to create transcribe task for recording {recording_id}: {e}")
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



