"""API endpoints для recordings с multi-tenancy support."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from api.core.context import ServiceContext
from api.core.dependencies import get_service_context
from api.repositories.recording_repos import RecordingAsyncRepository
from logger import get_logger
from models import ProcessingStatus
from transcription_module.factory import TranscriptionServiceFactory
from video_download_module.downloader import ZoomDownloader
from video_processing_module.video_processor import VideoProcessor
from video_upload_module.factory import UploaderFactory

router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])
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
    Скачать запись из Zoom.

    Args:
        recording_id: ID записи
        force: Пересохранить если уже скачано
        ctx: Service context

    Returns:
        Результат скачивания
    """
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
            }

    try:
        # Создаем downloader
        user_download_dir = f"media/user_{ctx.user_id}/video/unprocessed"
        downloader = ZoomDownloader(download_dir=user_download_dir)

        # Преобразуем RecordingModel в MeetingRecording для downloader
        from models import MeetingRecording

        meeting_id = recording.source.source_key if recording.source else str(recording.id)
        file_size = recording.source.meta.get("file_size", 0) if recording.source and recording.source.meta else recording.video_file_size or 0

        meeting_recording = MeetingRecording(
            {
                "id": meeting_id,
                "topic": recording.display_name,
                "start_time": recording.start_time.isoformat(),
                "duration": recording.duration or 0,
                "recording_files": [
                    {
                        "file_type": "MP4",
                        "file_size": file_size,
                        "download_url": download_url,
                        "recording_type": "shared_screen_with_speaker_view",
                    }
                ],
            }
        )
        meeting_recording.db_id = recording.id

        # Скачиваем
        success = await downloader.download_recording(
            meeting_recording, force_download=force
        )

        if success:
            # Обновляем запись в БД
            recording.local_video_path = meeting_recording.local_video_path
            recording.status = ProcessingStatus.DOWNLOADED
            await recording_repo.update(recording)
            await ctx.session.commit()

            logger.info(f"Downloaded recording {recording_id} for user {ctx.user_id}")

            return {
                "success": True,
                "recording_id": recording_id,
                "local_video_path": recording.local_video_path,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Download failed",
            )

    except Exception as e:
        logger.error(f"Download failed for recording {recording_id}: {e}", exc_info=True)
        await ctx.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Download failed: {str(e)}",
        )


@router.post("/{recording_id}/process")
async def process_recording(
    recording_id: int,
    config: ProcessVideoRequest = ProcessVideoRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Обработать видео (FFmpeg - удаление тишины).

    Args:
        recording_id: ID записи
        config: Конфигурация обработки
        ctx: Service context

    Returns:
        Результат обработки
    """
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

    try:
        # Создаем processor
        user_processed_dir = f"media/user_{ctx.user_id}/video/processed"
        processor = VideoProcessor(
            silence_threshold=config.silence_threshold,
            min_silence_duration=config.min_silence_duration,
            padding_before=config.padding_before,
            padding_after=config.padding_after,
            output_dir=user_processed_dir,
        )

        # Преобразуем RecordingModel в MeetingRecording
        from models import MeetingRecording

        meeting_id = recording.source.source_key if recording.source else str(recording.id)

        meeting_recording = MeetingRecording(
            {
                "id": meeting_id,
                "topic": recording.display_name,
                "start_time": recording.start_time.isoformat(),
                "duration": recording.duration or 0,
            }
        )
        meeting_recording.db_id = recording.id
        meeting_recording.local_video_path = recording.local_video_path
        meeting_recording.status = recording.status

        # Обрабатываем
        success = await processor.process_recording(meeting_recording)

        if success:
            # Обновляем запись в БД
            recording.processed_video_path = meeting_recording.processed_video_path
            recording.status = ProcessingStatus.PROCESSED
            await recording_repo.update(recording)
            await ctx.session.commit()

            logger.info(f"Processed recording {recording_id} for user {ctx.user_id}")

            return {
                "success": True,
                "recording_id": recording_id,
                "processed_video_path": recording.processed_video_path,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Processing failed",
            )

    except Exception as e:
        logger.error(f"Processing failed for recording {recording_id}: {e}", exc_info=True)
        await ctx.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Processing failed: {str(e)}",
        )


@router.post("/batch-process")
async def batch_process_recordings(
    recording_ids: list[int] = Query(..., description="Список ID записей"),
    config: FullPipelineRequest = FullPipelineRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Пакетная обработка нескольких записей.

    Args:
        recording_ids: Список ID записей
        config: Конфигурация пайплайна
        ctx: Service context

    Returns:
        Результаты обработки для каждой записи
    """
    results = []

    for recording_id in recording_ids:
        try:
            result = await full_pipeline_processing(
                recording_id=recording_id, config=config, ctx=ctx
            )
            results.append(result)
        except HTTPException as e:
            results.append(
                {
                    "recording_id": recording_id,
                    "status": "failed",
                    "error": e.detail,
                }
            )
        except Exception as e:
            results.append(
                {
                    "recording_id": recording_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

    return {
        "total": len(recording_ids),
        "processed": len([r for r in results if r.get("status") != "failed"]),
        "failed": len([r for r in results if r.get("status") == "failed"]),
        "results": results,
    }


@router.post("/{recording_id}/full-pipeline")
async def full_pipeline_processing(
    recording_id: int,
    config: FullPipelineRequest = FullPipelineRequest(),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Полный пайплайн обработки: download → process → transcribe → upload.

    Args:
        recording_id: ID записи
        config: Конфигурация пайплайна
        ctx: Service context

    Returns:
        Результаты обработки
    """
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    results: dict[str, Any] = {
        "recording_id": recording_id,
        "steps_completed": [],
        "errors": [],
    }

    try:
        # STEP 1: Download
        if config.download and not recording.local_video_path:
            try:
                download_result = await download_recording(
                    recording_id=recording_id, force=False, ctx=ctx
                )
                results["steps_completed"].append("download")
                results["download"] = download_result
                # Обновляем объект
                recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            except Exception as e:
                results["errors"].append(f"Download failed: {str(e)}")
                logger.error(f"Download step failed: {e}")

        # STEP 2: Process
        if config.process and not recording.processed_video_path:
            try:
                process_result = await process_recording(
                    recording_id=recording_id, config=config.process_config, ctx=ctx
                )
                results["steps_completed"].append("process")
                results["process"] = process_result
                # Обновляем объект
                recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            except Exception as e:
                results["errors"].append(f"Processing failed: {str(e)}")
                logger.error(f"Processing step failed: {e}")

        # STEP 3: Transcribe
        if config.transcribe:
            try:
                transcribe_result = await transcribe_recording(
                    recording_id=recording_id, granularity=config.granularity, ctx=ctx
                )
                results["steps_completed"].append("transcribe")
                results["transcribe"] = transcribe_result
            except Exception as e:
                results["errors"].append(f"Transcription failed: {str(e)}")
                logger.error(f"Transcription step failed: {e}")

        # STEP 4: Upload
        if config.upload and config.platforms:
            upload_results = []
            for platform in config.platforms:
                try:
                    preset_id = (
                        config.preset_ids.get(platform) if config.preset_ids else None
                    )
                    upload_result = await upload_recording(
                        recording_id=recording_id,
                        platform=platform,
                        preset_id=preset_id,
                        ctx=ctx,
                    )
                    upload_results.append(upload_result)
                except Exception as e:
                    results["errors"].append(f"Upload to {platform} failed: {str(e)}")
                    logger.error(f"Upload to {platform} failed: {e}")

            if upload_results:
                results["steps_completed"].append("upload")
                results["upload"] = upload_results

        # Финальный статус
        if not results["errors"]:
            results["status"] = "completed"
        elif results["steps_completed"]:
            results["status"] = "partially_completed"
        else:
            results["status"] = "failed"

        return results

    except Exception as e:
        logger.error(f"Full pipeline failed for recording {recording_id}: {e}", exc_info=True)
        await ctx.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {str(e)}",
        )


@router.post("/{recording_id}/transcribe")
async def transcribe_recording(
    recording_id: int,
    granularity: str = "long",
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Транскрибировать запись с использованием user credentials.

    Args:
        recording_id: ID записи
        granularity: Режим извлечения тем ("short" | "long")
        ctx: Service context с user_id и session

    Returns:
        Результаты транскрибации
    """
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

    try:
        # Создаем TranscriptionService для пользователя
        transcription_service = await TranscriptionServiceFactory.create_for_user(
            session=ctx.session,
            user_id=ctx.user_id
        )

        # Выполняем транскрибацию
        result = await transcription_service.process_audio(
            audio_path=audio_path,
            recording_id=recording_id,
            recording_topic=recording.display_name,
            recording_start_time=recording.start_time.isoformat(),
            granularity=granularity,
        )

        # Сохраняем результаты в БД
        await recording_repo.save_transcription_result(
            recording=recording,
            transcription_dir=result["transcription_dir"],
            transcription_info=result.get("fireworks_raw", {}),
            topic_timestamps=result["topic_timestamps"],
            main_topics=result["main_topics"],
        )

        await ctx.session.commit()

        logger.info(
            f"Transcription completed for recording {recording_id} (user {ctx.user_id})"
        )

        return {
            "success": True,
            "recording_id": recording_id,
            "transcription_dir": result["transcription_dir"],
            "topics_count": len(result["topic_timestamps"]),
            "main_topics_count": len(result["main_topics"]),
            "main_topics": result["main_topics"],
            "language": result.get("language", "ru"),
        }

    except ValueError as e:
        logger.error(f"Transcription failed for recording {recording_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during transcription: {e}", exc_info=True)
        await ctx.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {str(e)}"
        )


@router.post("/{recording_id}/upload/{platform}")
async def upload_recording(
    recording_id: int,
    platform: str,
    preset_id: int | None = None,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Загрузить запись на платформу с использованием user credentials.

    Args:
        recording_id: ID записи
        platform: Платформа (youtube, vk)
        preset_id: ID output preset (опционально)
        ctx: Service context

    Returns:
        Результаты загрузки
    """
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

    try:
        # Создаем uploader для платформы
        if preset_id:
            uploader = await UploaderFactory.create_uploader_by_preset_id(
                session=ctx.session,
                user_id=ctx.user_id,
                preset_id=preset_id
            )
        else:
            uploader = await UploaderFactory.create_uploader(
                session=ctx.session,
                user_id=ctx.user_id,
                platform=platform
            )

        # Получаем параметры для загрузки
        title = recording.display_name
        description = f"Uploaded on {recording.start_time.strftime('%Y-%m-%d')}"

        # Добавляем темы в описание, если есть
        if recording.main_topics:
            topics_str = ", ".join(recording.main_topics[:5])
            description += f"\n\nТемы: {topics_str}"

        # Аутентификация
        auth_success = await uploader.authenticate()
        if not auth_success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Failed to authenticate with {platform}"
            )

        logger.info(
            f"Starting upload of recording {recording_id} to {platform} "
            f"(user {ctx.user_id})"
        )

        # Загрузка
        upload_result = await uploader.upload_video(
            video_path=video_path,
            title=title,
            description=description,
        )

        if not upload_result or not upload_result.success:
            error_msg = upload_result.error if upload_result else 'Unknown error'
            logger.error(f"Upload failed: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Upload failed: {error_msg}"
            )

        # Сохраняем результаты в БД
        target_type_map = {
            "youtube": "YOUTUBE",
            "vk": "VK",
        }

        target_type = target_type_map.get(platform.lower(), platform.upper())

        await recording_repo.save_upload_result(
            recording=recording,
            target_type=target_type,
            preset_id=preset_id,
            video_id=upload_result.video_id,
            video_url=upload_result.video_url,
            target_meta={
                "platform": platform,
                "uploaded_by_api": True,
            }
        )

        await ctx.session.commit()

        logger.info(
            f"Upload completed for recording {recording_id} to {platform} "
            f"(user {ctx.user_id}): {upload_result.video_url}"
        )

        return {
            "success": True,
            "recording_id": recording_id,
            "platform": platform,
            "video_id": upload_result.video_id,
            "video_url": upload_result.video_url,
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Upload failed for recording {recording_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}", exc_info=True)
        await ctx.session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("/credentials/status")
async def check_credentials_status(
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Проверить наличие необходимых credentials у пользователя.

    Args:
        ctx: Service context

    Returns:
        Статус credentials для разных платформ
    """
    platforms = await ctx.config_helper.list_available_platforms()

    status_map = {}
    for platform in ["zoom", "youtube", "vk", "fireworks", "deepseek", "openai"]:
        status_map[platform] = await ctx.config_helper.has_credentials_for_platform(platform)

    return {
        "user_id": ctx.user_id,
        "available_platforms": platforms,
        "credentials_status": status_map,
    }

