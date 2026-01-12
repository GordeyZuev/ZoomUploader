"""API endpoints для recordings с multi-tenancy support."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Union

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
    is_mapped: bool = False
    template_id: int | None = None
    template_name: str | None = None
    input_source: dict | None = None

    class Config:
        from_attributes = True


class DetailedRecordingResponse(RecordingResponse):
    """Расширенная response модель с детальной информацией."""

    videos: dict | None = None
    audio: dict | None = None
    transcription: dict | None = None
    topics: dict | None = None
    subtitles: dict | None = None
    processing_stages: list[dict] | None = None
    uploads: dict | None = None


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
    """Request для полного пайплайна (deprecated, use template-driven config)."""

    download: bool = True
    process: bool = True
    transcribe: bool = True
    upload: bool = False
    platforms: list[str] = []
    preset_ids: dict[str, int] | None = None
    granularity: str = "long"
    process_config: ProcessVideoRequest = ProcessVideoRequest()


class ConfigOverrideRequest(BaseModel):
    """
    Гибкий request для override конфигурации в full-pipeline.

    Поддерживает любые поля из template config для переопределения.
    """

    processing_config: dict | None = None
    metadata_config: dict | None = None
    output_config: dict | None = None


def _build_manual_override(config: FullPipelineRequest) -> dict:
    """Convert FullPipelineRequest to manual_override dict for full_pipeline_task."""
    return {
        "download": {"auto_download": config.download},
        "enable_processing": config.process,
        "transcription": {
            "enable_transcription": config.transcribe,
            "granularity": config.granularity,
        },
        "upload": {
            "auto_upload": config.upload,
            "default_platforms": config.platforms,
        },
        "silence_threshold": config.process_config.silence_threshold,
        "min_silence_duration": config.process_config.min_silence_duration,
        "padding_before": config.process_config.padding_before,
        "padding_after": config.process_config.padding_after,
        # preset_ids будут резолвиться через output_config
    }


def _build_override_from_flexible(config: ConfigOverrideRequest) -> dict:
    """
    Convert ConfigOverrideRequest to manual_override dict.

    Returns a dict that will be merged with resolved config hierarchy.
    """
    override = {}

    if config.processing_config:
        override["processing_config"] = config.processing_config

    if config.metadata_config:
        override["metadata_config"] = config.metadata_config

    if config.output_config:
        override["output_config"] = config.output_config

    return override


# ============================================================================
# CRUD Endpoints
# ============================================================================


@router.get("", response_model=RecordingListResponse)
async def list_recordings(
    status_filter: str | None = Query(None, description="Фильтр по статусу"),
    failed: bool | None = Query(None, description="Только failed записи"),
    mapped: bool | None = Query(None, description="Фильтр по is_mapped (true/false/null=все)"),
    include_blank: bool = Query(False, description="Include blank records (short/small)"),
    from_date: str | None = Query(None, description="Фильтр: start_time >= from_date (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="Фильтр: start_time <= to_date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Получить список записей пользователя.

    Args:
        status_filter: Фильтр по статусу (INITIALIZED, DOWNLOADED, PROCESSED, etc.)
        failed: Только failed записи
        mapped: Фильтр по is_mapped (true - только mapped, false - только unmapped, null - все)
        include_blank: Include blank records (default: False - скрывает blank records)
        from_date: Фильтр по дате начала (YYYY-MM-DD)
        to_date: Фильтр по дате окончания (YYYY-MM-DD)
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

    if mapped is not None:
        recordings = [r for r in recordings if r.is_mapped == mapped]

    # Фильтр blank_record (по умолчанию скрываем blank records)
    if not include_blank:
        recordings = [r for r in recordings if not r.blank_record]

    # Фильтры по дате
    if from_date:
        from utils.date_utils import parse_date
        from_dt_str = parse_date(from_date)
        from_dt = datetime.strptime(from_dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        recordings = [r for r in recordings if r.start_time >= from_dt]

    if to_date:
        from utils.date_utils import parse_date
        to_dt_str = parse_date(to_date)
        to_dt = datetime.strptime(to_dt_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # End of day
        to_dt = to_dt.replace(hour=23, minute=59, second=59)
        recordings = [r for r in recordings if r.start_time <= to_dt]

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
                is_mapped=r.is_mapped,
                template_id=r.template_id,
                template_name=r.template.name if r.template else None,
                input_source={
                    "id": r.input_source.id,
                    "name": r.input_source.name,
                    "type": r.input_source.source_type,
                } if r.input_source else None,
            )
            for r in paginated_recordings
        ],
        page=page,
        per_page=per_page,
    )


@router.get("/{recording_id}", response_model=Union[RecordingResponse, DetailedRecordingResponse])
async def get_recording(
    recording_id: int,
    detailed: bool = Query(False, description="Включить детальную информацию (файлы, транскрипция, топики, загрузки)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Получить одну запись по ID.

    Args:
        recording_id: ID записи
        detailed: Если True, включает детальную информацию о файлах, транскрипции, топиках, субтитрах и загрузках
        ctx: Service context

    Returns:
        Recording (базовая или детальная информация)
    """
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Если не нужна детальная информация, возвращаем базовую через Pydantic модель
    if not detailed:
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
            is_mapped=recording.is_mapped,
            template_id=recording.template_id,
            template_name=recording.template.name if recording.template else None,
            input_source={
                "id": recording.input_source.id,
                "name": recording.input_source.name,
                "type": recording.input_source.source_type,
            } if recording.input_source else None,
        )

    # Детальная информация
    from transcription_module.manager import get_transcription_manager

    transcription_manager = get_transcription_manager()

    # Базовая информация (общие поля)
    base_data = {
        "id": recording.id,
        "meeting_id": recording.source.source_key if recording.source else None,
        "display_name": recording.display_name,
        "start_time": recording.start_time.isoformat(),
        "duration": recording.duration,
        "status": recording.status.value,
        "local_video_path": recording.local_video_path,
        "processed_video_path": recording.processed_video_path,
        "transcription_dir": recording.transcription_dir,
        "main_topics": recording.main_topics,
        "failed": recording.failed,
        "failed_reason": recording.failed_reason,
        "is_mapped": recording.is_mapped,
        "template_id": recording.template_id,
        "template_name": recording.template.name if recording.template else None,
        "input_source": {
            "id": recording.input_source.id,
            "name": recording.input_source.name,
            "type": recording.input_source.source_type,
        } if recording.input_source else None,
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

    # Аудио файлы
    audio_info = {}
    if recording.processed_audio_path:
        audio_path = Path(recording.processed_audio_path)
        if audio_path.exists():
            audio_info = {
                "path": str(audio_path),
                "size_mb": round(audio_path.stat().st_size / (1024 * 1024), 2),
                "exists": True,
            }
        else:
            audio_info = {
                "path": str(audio_path),
                "exists": False,
                "size_mb": None,
            }

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

    # Субтитры
    subtitles = {}
    cache_dir = transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "cache"
    for fmt in ["srt", "vtt"]:
        subtitle_path = cache_dir / f"subtitles.{fmt}"
        subtitles[fmt] = {
            "path": str(subtitle_path) if subtitle_path.exists() else None,
            "exists": subtitle_path.exists(),
            "size_kb": round(subtitle_path.stat().st_size / 1024, 2) if subtitle_path.exists() else None,
        }

    # Этапы обработки
    processing_stages = None
    if hasattr(recording, "processing_stages") and recording.processing_stages:
        processing_stages = [
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
    if hasattr(recording, "outputs") and recording.outputs:
        for target in recording.outputs:
            platform = target.target_type.value if hasattr(target.target_type, "value") else str(target.target_type)

            # Базовая информация
            upload_info = {
                "status": target.status.value if hasattr(target.status, "value") else str(target.status),
                "url": target.target_meta.get("video_url") or target.target_meta.get("target_link") if target.target_meta else None,
                "video_id": target.target_meta.get("video_id") if target.target_meta else None,
                "uploaded_at": target.uploaded_at.isoformat() if target.uploaded_at else None,
                "failed": target.failed,
                "retry_count": target.retry_count,
            }

            # Добавляем информацию о preset если есть
            if target.preset:
                upload_info["preset"] = {
                    "id": target.preset.id,
                    "name": target.preset.name,
                }

            uploads[platform] = upload_info

    # Создаем DetailedRecordingResponse
    return DetailedRecordingResponse(
        **base_data,
        videos=videos if videos else None,
        audio=audio_info if audio_info else None,
        transcription=transcription_data,
        topics=topics_data,
        subtitles=subtitles,
        processing_stages=processing_stages,
        uploads=uploads if uploads else None,
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

            # Skip blank records
            if recording.blank_record:
                tasks.append({
                    "recording_id": recording_id,
                    "status": "skipped",
                    "error": "Blank record (too short or too small)",
                    "task_id": None,
                })
                continue

            # Запускаем задачу для этой записи (template-driven)
            manual_override = _build_manual_override(config)
            task = full_pipeline_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                manual_override=manual_override,
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
    config: ConfigOverrideRequest = ConfigOverrideRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Полный пайплайн обработки (асинхронная задача): download → process → transcribe → upload.

    Supports flexible config overrides:
    - processing_config: Override processing settings (transcription, silence detection, etc.)
    - metadata_config: Override metadata (title, description, playlists, albums, etc.)
    - output_config: Override output settings (preset_ids, auto_upload, etc.)

    Args:
        recording_id: ID записи
        config: Гибкие overrides для конфигурации (опционально)
        ctx: Service context

    Returns:
        Task ID для проверки статуса

    Example:
        ```json
        {
          "processing_config": {
            "transcription": {"granularity": "short"}
          },
          "metadata_config": {
            "vk": {"album_id": "63"},
            "youtube": {"playlist_id": "PLxxx"}
          }
        }
        ```

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

    # Resolve actual config to show in response
    from api.services.config_resolver import ConfigResolver
    config_resolver = ConfigResolver(ctx.session)
    output_config = await config_resolver.resolve_output_config(recording, ctx.user_id)

    # Determine actual upload flag from resolved config
    actual_upload = output_config.get("upload", False) or output_config.get("auto_upload", False)

    # Build manual override from flexible config
    manual_override = _build_override_from_flexible(config)

    task = full_pipeline_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        manual_override=manual_override,
    )

    logger.info(
        f"Full pipeline task {task.id} created for recording {recording_id}, user {ctx.user_id}, "
        f"overrides: {list(manual_override.keys())}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Full pipeline task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
        "config_overrides": manual_override if manual_override else None,
    }


@router.post("/{recording_id}/transcribe")
async def transcribe_recording(
    recording_id: int,
    use_batch_api: bool = Query(False, description="Использовать Batch API (дешевле, но требует polling)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Транскрибировать запись (асинхронная задача) с использованием АДМИНСКИХ кредов.

    ⚠️ ВАЖНО: Создает только master.json (words, segments).
    Для извлечения тем используйте отдельный endpoint /topics.

    Args:
        recording_id: ID записи
        use_batch_api: Использовать Batch API (экономия ~50%, но дольше waiting)
        ctx: Service context с user_id и session

    Returns:
        Task ID для проверки статуса

    Note:
        Использует АДМИНСКИЕ креды для транскрибации через Fireworks API.

        Batch API (use_batch_api=true):
        - Дешевле ~50% чем синхронный API
        - Требует polling для получения результата
        - Время ожидания: обычно несколько минут
        - Документация: https://docs.fireworks.ai/api-reference/create-batch-request

        Это асинхронная операция. Используйте GET /api/v1/tasks/{task_id}
        для проверки статуса выполнения и получения результатов.
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_transcription
    from api.tasks.processing import batch_transcribe_recording_task, transcribe_recording_task

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

    # Выбираем режим: Batch API или обычный
    if use_batch_api:
        # Batch API mode: submit batch job, затем polling
        from fireworks_module import FireworksConfig, FireworksTranscriptionService

        fireworks_config = FireworksConfig.from_file("config/fireworks_creds.json")

        # Проверяем наличие account_id
        if not fireworks_config.account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Batch API недоступен: account_id не настроен в config/fireworks_creds.json. "
                "Добавьте account_id из Fireworks dashboard или используйте use_batch_api=false."
            )

        fireworks_service = FireworksTranscriptionService(fireworks_config)

        # Submit batch job
        try:
            batch_result = await fireworks_service.submit_batch_transcription(
                audio_path=audio_path,
                language=fireworks_config.language,
                prompt=None,  # TODO: можно добавить prompt из конфига
            )
            batch_id = batch_result.get("batch_id")

            if not batch_id:
                raise ValueError("Batch API не вернул batch_id")

            logger.info(
                f"Batch transcription submitted | batch_id={batch_id} | recording={recording_id} | user={ctx.user_id}"
            )

            # Запускаем polling task
            task = batch_transcribe_recording_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                batch_id=batch_id,
                poll_interval=10.0,  # 10 секунд
                max_wait_time=3600.0,  # 1 час
            )

            logger.info(
                f"Batch polling task {task.id} created | batch_id={batch_id} | recording={recording_id} | user={ctx.user_id}"
            )

            return {
                "success": True,
                "task_id": task.id,
                "recording_id": recording_id,
                "batch_id": batch_id,
                "mode": "batch_api",
                "status": "queued",
                "message": "Batch transcription submitted. Polling task queued.",
                "check_status_url": f"/api/v1/tasks/{task.id}",
            }

        except Exception as e:
            logger.error(f"Failed to submit batch transcription: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit batch transcription: {str(e)}"
            )
    else:
        # Обычный режим (синхронный API)
        task = transcribe_recording_task.delay(
            recording_id=recording_id,
            user_id=ctx.user_id,
        )

        logger.info(f"Transcription task {task.id} created for recording {recording_id}, user {ctx.user_id}")

        return {
            "success": True,
            "task_id": task.id,
            "recording_id": recording_id,
            "mode": "sync_api",
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

            # Skip blank records
            if recording.blank_record:
                tasks.append({
                    "recording_id": recording_id,
                    "status": "skipped",
                    "error": "Blank record (too short or too small)",
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


@router.post("/{recording_id}/retry-upload")
async def retry_failed_uploads(
    recording_id: int,
    platforms: list[str] | None = None,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Повторить загрузку для failed output_targets.

    Если platforms не указаны: retry все с status=FAILED
    Если platforms указаны: retry только эти платформы
    Использует актуальный preset_id из output_target

    Args:
        recording_id: ID записи
        platforms: Список платформ для retry (опционально)
        ctx: Service context

    Returns:
        Список задач retry upload
    """
    from api.tasks.upload import upload_recording_to_platform

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Получить запись
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Получить failed output_targets
    failed_targets = []
    for output in recording.outputs:
        if output.failed or output.status == "FAILED":
            # Если указаны конкретные платформы, фильтруем
            if platforms:
                if output.target_type.lower() in [p.lower() for p in platforms]:
                    failed_targets.append(output)
            else:
                failed_targets.append(output)

    if not failed_targets:
        return {
            "message": "No failed uploads found for retry",
            "recording_id": recording_id,
            "tasks": [],
        }

    # Запустить retry для каждого failed target
    tasks = []
    for target in failed_targets:
        try:
            task = upload_recording_to_platform.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                platform=target.target_type.lower(),
                preset_id=target.preset_id,
            )

            tasks.append({
                "platform": target.target_type,
                "task_id": str(task.id),
                "status": "queued",
                "previous_attempts": target.retry_count,
            })

            logger.info(
                f"Queued retry upload for recording {recording_id} to {target.target_type} "
                f"(attempt {target.retry_count + 1})"
            )

        except Exception as e:
            logger.error(f"Failed to queue retry for {target.target_type}: {e}")
            tasks.append({
                "platform": target.target_type,
                "status": "error",
                "error": str(e),
            })

    return {
        "message": f"Retry queued for {len([t for t in tasks if t['status'] == 'queued'])} platforms",
        "recording_id": recording_id,
        "tasks": tasks,
    }


@router.get("/{recording_id}/config")
async def get_recording_config(
    recording_id: int,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Получить текущую resolved конфигурацию recording для редактирования.

    Returns:
    - processing_config: resolved config (user + template если есть)
    - output_config: preset_ids для платформ
    - has_manual_override: bool - есть ли сохраненный manual config
    - template_name: название template если привязан

    NOTE: Metadata (title, description, tags) настраивается в output_preset.preset_metadata,
    а не в recording config.

    Args:
        recording_id: ID записи
        ctx: Service context

    Returns:
        Resolved configuration для редактирования
    """
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Получить запись
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Resolve configuration
    config_resolver = ConfigResolver(ctx.session)
    config = await config_resolver.get_base_config_for_edit(recording, ctx.user_id)

    return {
        "recording_id": recording_id,
        "is_mapped": recording.is_mapped,
        **config,
    }


@router.put("/{recording_id}/config")
async def update_recording_config(
    recording_id: int,
    processing_config: dict | None = None,
    output_config: dict | None = None,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Сохранить user overrides в recording.processing_preferences.

    Логика:
    1. Получить current resolved config (base from template)
    2. Применить изменения из request
    3. Сохранить только overrides в recording.processing_preferences

    Теперь этот recording будет использовать template config + user overrides.

    NOTE: Metadata (title, description, tags) настраивается в output_preset.preset_metadata,
    а не здесь.

    Args:
        recording_id: ID записи
        processing_config: Конфигурация обработки (опционально)
        output_config: Конфигурация output presets (опционально)
        ctx: Service context

    Returns:
        Обновленная конфигурация
    """
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Получить запись
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Get config resolver
    config_resolver = ConfigResolver(ctx.session)

    # Save only user overrides (not full config)
    new_preferences = recording.processing_preferences or {}

    if processing_config is not None:
        if "processing_config" not in new_preferences:
            new_preferences["processing_config"] = {}
        new_preferences["processing_config"] = config_resolver._merge_configs(
            new_preferences.get("processing_config", {}),
            processing_config
        )

    if output_config is not None:
        if "output_config" not in new_preferences:
            new_preferences["output_config"] = {}
        new_preferences["output_config"] = config_resolver._merge_configs(
            new_preferences.get("output_config", {}),
            output_config
        )

    # Save overrides to recording.processing_preferences
    recording.processing_preferences = new_preferences if new_preferences else None
    await ctx.session.commit()

    logger.info(f"Updated manual config for recording {recording_id}")

    # Get effective config after update
    effective_config = await config_resolver.resolve_processing_config(recording, ctx.user_id)

    return {
        "recording_id": recording_id,
        "message": "Configuration saved",
        "has_manual_override": bool(new_preferences),
        "overrides": new_preferences,
        "effective_config": effective_config,
    }


@router.delete("/{recording_id}/config")
async def reset_to_template(
    recording_id: int,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Сбросить пользовательские настройки и вернуться к шаблону.

    Очищает recording.processing_preferences, после чего запись будет
    использовать только конфигурацию из шаблона.

    Args:
        recording_id: ID записи
        ctx: Service context

    Returns:
        Обновленная конфигурация
    """
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Получить запись
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Очистить overrides
    recording.processing_preferences = None
    await ctx.session.commit()

    # Get effective config (from template)
    config_resolver = ConfigResolver(ctx.session)
    effective_config = await config_resolver.resolve_processing_config(recording, ctx.user_id)

    logger.info(f"Reset recording {recording_id} to template configuration")

    return {
        "recording_id": recording_id,
        "message": "Reset to template configuration",
        "has_manual_override": False,
        "effective_config": effective_config,
    }


@router.post("/{recording_id}/config/save-as-template")
async def save_config_as_template(
    recording_id: int,
    name: str,
    description: str | None = None,
    match_pattern: str | None = None,
    match_source_id: bool = False,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Сохранить текущую конфигурацию recording как новый template.

    Use case: User настроил manual config для одного видео,
    хочет переиспользовать для будущих видео.

    Создает новый template с:
    - processing_config = recording.processing_preferences.processing_config
    - output_config = recording.processing_preferences.output_config
    - matching_rules = из request (match_pattern, match_source_id)

    NOTE: Metadata (title, description, tags) настраивается в output_preset.preset_metadata,
    а не в template.

    Args:
        recording_id: ID записи
        name: Название template
        description: Описание template (опционально)
        match_pattern: Паттерн для matching (опционально, default: exact match)
        match_source_id: Включить source_id в matching rules
        ctx: Service context

    Returns:
        Созданный template
    """
    from database.template_models import RecordingTemplateModel

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Получить запись
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    if not recording.processing_preferences:
        raise HTTPException(
            status_code=400,
            detail="Recording has no manual configuration to save as template"
        )

    # Build matching rules
    matching_rules = {}

    if match_pattern:
        # Use provided pattern
        matching_rules["patterns"] = [match_pattern]
    else:
        # Use exact match with recording name
        matching_rules["exact_matches"] = [recording.display_name]

    if match_source_id and recording.input_source_id:
        matching_rules["source_ids"] = [recording.input_source_id]

    # Extract configs from processing_preferences
    processing_config = recording.processing_preferences.get("processing_config", {})
    output_config = recording.processing_preferences.get("output_config", {})

    # Create template
    template = RecordingTemplateModel(
        user_id=ctx.user_id,
        name=name,
        description=description or f"Created from recording '{recording.display_name}'",
        matching_rules=matching_rules,
        processing_config=processing_config if processing_config else None,
        output_config=output_config if output_config else None,
        is_active=True,
        is_draft=False,
    )

    ctx.session.add(template)
    await ctx.session.commit()
    await ctx.session.refresh(template)

    logger.info(f"Created template '{name}' from recording {recording_id}")

    return {
        "template_id": template.id,
        "name": template.name,
        "message": "Template created successfully",
        "matching_rules": template.matching_rules,
    }


@router.post("/{recording_id}/reset")
async def reset_recording(
    recording_id: int,
    delete_files: bool = Query(True, description="Удалить все файлы (видео, аудио, транскрипция)"),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Сбросить запись к начальному состоянию.

    Что делает:
    - Удаляет все обработанные файлы (видео, аудио, транскрипция, субтитры)
    - Очищает метаданные (topics, transcription_info)
    - Удаляет output_targets
    - Удаляет processing_stages
    - Возвращает статус в INITIALIZED
    - Очищает failed флаг и failed_reason

    Опционально сохраняет:
    - local_video_path (скачанное видео) - если delete_files=False
    - template_id, is_mapped
    - processing_preferences (manual config)

    Args:
        recording_id: ID записи
        delete_files: Удалить все файлы (default: True)
        ctx: Service context

    Returns:
        Результат reset операции
    """
    from pathlib import Path

    from sqlalchemy import delete

    from database.models import OutputTargetModel, ProcessingStageModel

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    deleted_files = []
    errors = []

    # Delete files if requested
    if delete_files:
        files_to_delete = []

        # Local video
        if recording.local_video_path:
            files_to_delete.append(("local_video", recording.local_video_path))

        # Processed video
        if recording.processed_video_path:
            files_to_delete.append(("processed_video", recording.processed_video_path))

        # Processed audio file
        if recording.processed_audio_path:
            audio_file = Path(recording.processed_audio_path)
            if audio_file.exists():
                # Удаляем файл и его родительскую директорию если она пустая
                files_to_delete.append(("processed_audio_file", str(audio_file)))
                audio_dir = audio_file.parent
                if audio_dir.exists() and not any(audio_dir.iterdir()):
                    files_to_delete.append(("empty_audio_dir", str(audio_dir)))

        # Transcription directory
        if recording.transcription_dir:
            files_to_delete.append(("transcription_dir", recording.transcription_dir))

        # Delete files
        for file_type, file_path in files_to_delete:
            try:
                path = Path(file_path)
                if path.exists():
                    if path.is_dir():
                        import shutil
                        shutil.rmtree(path)
                        deleted_files.append({"type": file_type, "path": str(path), "is_dir": True})
                    else:
                        path.unlink()
                        deleted_files.append({"type": file_type, "path": str(path), "is_dir": False})
            except Exception as e:
                errors.append({"type": file_type, "path": file_path, "error": str(e)})
                logger.error(f"Failed to delete {file_type} at {file_path}: {e}")

    # Clear recording metadata
    recording.local_video_path = None
    recording.processed_video_path = None
    recording.processed_audio_path = None
    recording.transcription_dir = None
    recording.topic_timestamps = None
    recording.main_topics = None
    recording.transcription_info = None
    recording.failed = False
    recording.failed_reason = None
    recording.status = ProcessingStatus.INITIALIZED

    # Delete output_targets
    await ctx.session.execute(
        delete(OutputTargetModel).where(OutputTargetModel.recording_id == recording_id)
    )

    # Delete processing_stages
    await ctx.session.execute(
        delete(ProcessingStageModel).where(ProcessingStageModel.recording_id == recording_id)
    )

    await ctx.session.commit()

    logger.info(
        f"Reset recording {recording_id}: deleted {len(deleted_files)} files, "
        f"{len(errors)} errors, status -> INITIALIZED"
    )

    return {
        "success": True,
        "recording_id": recording_id,
        "message": "Recording reset to initial state",
        "deleted_files": deleted_files,
        "errors": errors,
        "status": "INITIALIZED",
        "preserved": {
            "template_id": recording.template_id,
            "is_mapped": recording.is_mapped,
            "processing_preferences": bool(recording.processing_preferences),
        }
    }


@router.post("/batch/process-mapped")
async def batch_process_mapped_recordings(
    template_id: int | None = None,
    source_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Запустить full_pipeline для всех recordings с is_mapped=true.

    Фильтры:
    - template_id: обработать только recordings этого template
    - source_id: обработать только recordings из этого source
    - status: обработать только recordings с этим статусом (default: INITIALIZED)

    Args:
        template_id: ID шаблона для фильтрации (опционально)
        source_id: ID источника для фильтрации (опционально)
        status_filter: Статус для фильтрации (опционально)
        limit: Максимум записей для обработки
        ctx: Service context

    Returns:
        Информация о запущенных задачах
    """
    from sqlalchemy import select

    from api.tasks.processing import full_pipeline_task
    from database.models import RecordingModel

    # Build query
    query = (
        select(RecordingModel)
        .where(RecordingModel.user_id == ctx.user_id)
        .where(RecordingModel.is_mapped)
        .where(~RecordingModel.blank_record)  # Skip blank records
    )

    # Apply filters
    if template_id:
        query = query.where(RecordingModel.template_id == template_id)

    if source_id:
        query = query.where(RecordingModel.input_source_id == source_id)

    if status_filter:
        query = query.where(RecordingModel.status == status_filter)
    else:
        # Default: только INITIALIZED
        query = query.where(RecordingModel.status == ProcessingStatus.INITIALIZED.value)

    query = query.order_by(RecordingModel.created_at.asc())
    query = query.limit(limit)

    result = await ctx.session.execute(query)
    recordings = result.scalars().all()

    if not recordings:
        return {
            "message": "No mapped recordings found matching filters",
            "queued_count": 0,
            "task_ids": [],
        }

    # Queue full_pipeline for each recording (template-driven, no manual override)
    tasks = []
    for recording in recordings:
        try:
            task = full_pipeline_task.delay(
                recording_id=recording.id,
                user_id=ctx.user_id,
                manual_override=None,  # Use template config
            )

            tasks.append(str(task.id))

            logger.info(
                f"Queued full_pipeline for recording {recording.id} "
                f"(template_id={recording.template_id})"
            )

        except Exception as e:
            logger.error(f"Failed to queue recording {recording.id}: {e}")

    return {
        "message": f"Queued {len(tasks)} recordings for processing",
        "queued_count": len(tasks),
        "task_ids": tasks,
        "filters": {
            "template_id": template_id,
            "source_id": source_id,
            "status": status_filter or "INITIALIZED",
        },
    }


