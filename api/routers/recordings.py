"""Recording endpoints with multi-tenancy support"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from api.core.context import ServiceContext
from api.core.dependencies import get_service_context
from api.repositories.recording_repos import RecordingAsyncRepository
from api.schemas.recording.filters import RecordingFilters as RecordingFiltersSchema
from api.schemas.recording.operations import (
    BulkProcessDryRunResponse,
    ConfigSaveResponse,
    DryRunResponse,
    RecordingBulkOperationResponse,
    RecordingOperationResponse,
    ResetRecordingResponse,
    RetryUploadResponse,
)
from api.schemas.recording.request import (
    BulkDownloadRequest,
    BulkProcessRequest,
    BulkSubtitlesRequest,
    BulkTopicsRequest,
    BulkTranscribeRequest,
    BulkTrimRequest,
    BulkUploadRequest,
)
from api.schemas.recording.response import (
    OutputTargetResponse,
    PresetInfo,
    RecordingListItem,
    RecordingListResponse,
    RecordingResponse,
    SourceInfo,
    SourceResponse,
    UploadInfo,
)
from logger import get_logger
from models import ProcessingStatus
from models.recording import TargetStatus

router = APIRouter(prefix="/api/v1/recordings", tags=["Recordings"])
logger = get_logger()


# ============================================================================
# Request/Response Models (used only in this router - KISS)
# ============================================================================


class DetailedRecordingResponse(RecordingResponse):
    """Extended response model with detailed information."""

    videos: dict | None = None
    audio: dict | None = None
    transcription: dict | None = None
    topics: dict | None = None
    subtitles: dict | None = None
    processing_stages: list[dict] | None = None
    uploads: dict | None = None


class TrimVideoRequest(BaseModel):
    """Request for video trimming (FFmpeg - removing silence)."""

    silence_threshold: float = -40.0
    min_silence_duration: float = 2.0
    padding_before: float = 5.0
    padding_after: float = 5.0


class ConfigOverrideRequest(BaseModel):
    """
    Flexible request for override configuration in process endpoint.

    Supports any fields from template config for override.
    """

    processing_config: dict | None = None
    metadata_config: dict | None = None
    output_config: dict | None = None


def _build_override_from_flexible(config: ConfigOverrideRequest) -> dict:
    """
    Convert ConfigOverrideRequest to manual_override dictionary.

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
# Bulk Operations Helper Functions (DRY)
# ============================================================================


async def _resolve_recording_ids(
    recording_ids: list[int] | None,
    filters: RecordingFiltersSchema | None,
    limit: int,
    ctx: ServiceContext,
) -> list[int]:
    """
    Universal resolver for all bulk operations.

    Returns list of recording_ids from explicit list OR from filters.

    Args:
        recording_ids: Explicit list of IDs (priority)
        filters: Filters for automatic selection
        limit: Maximum number of records
        ctx: Service context

    Returns:
        List of recording IDs

    Raises:
        ValueError: If neither recording_ids nor filters are specified
    """
    if recording_ids:
        return recording_ids

    if filters:
        return await _query_recordings_by_filters(filters, limit, ctx)

    raise ValueError("Either recording_ids or filters must be specified")


async def _query_recordings_by_filters(
    filters: RecordingFiltersSchema,
    limit: int,
    ctx: ServiceContext,
) -> list[int]:
    """
    Build query by filters and return list of IDs.

    Reused in all bulk/* endpoints.

    Args:
        filters: Filters for selection
        limit: Maximum number of records
        ctx: Service context

    Returns:
        List of recording IDs
    """
    from sqlalchemy import select

    from database.models import RecordingModel

    query = select(RecordingModel.id).where(RecordingModel.user_id == ctx.user_id)

    # Apply filters
    if filters.template_id:
        query = query.where(RecordingModel.template_id == filters.template_id)

    if filters.source_id:
        query = query.where(RecordingModel.input_source_id == filters.source_id)

    if filters.status:
        # Handling special case "FAILED" through recording.failed
        has_failed = "FAILED" in filters.status
        other_statuses = [s for s in filters.status if s != "FAILED"]

        if has_failed and other_statuses:
            # Combination: (status IN [...] OR failed=true)
            from sqlalchemy import or_

            query = query.where(
                or_(
                    RecordingModel.status.in_(other_statuses),
                    RecordingModel.failed == True,  # noqa: E712
                )
            )
        elif has_failed:
            # Only failed
            query = query.where(RecordingModel.failed == True)  # noqa: E712
        else:
            # Regular statuses
            query = query.where(RecordingModel.status.in_(other_statuses))

    if filters.is_mapped is not None:
        query = query.where(RecordingModel.is_mapped == filters.is_mapped)

    if filters.failed is not None:
        query = query.where(RecordingModel.failed == filters.failed)

    if filters.exclude_blank:
        query = query.where(~RecordingModel.blank_record)

    if filters.search:
        query = query.where(RecordingModel.display_name.ilike(f"%{filters.search}%"))

    # Date filters
    if filters.from_date:
        from utils.date_utils import parse_from_date_to_datetime

        from_dt = parse_from_date_to_datetime(filters.from_date)
        query = query.where(RecordingModel.start_time >= from_dt)

    if filters.to_date:
        from utils.date_utils import parse_to_date_to_datetime

        to_dt = parse_to_date_to_datetime(filters.to_date)
        query = query.where(RecordingModel.start_time <= to_dt)

    # Sorting
    order_column = getattr(RecordingModel, filters.order_by, RecordingModel.created_at)
    if filters.order == "desc":
        query = query.order_by(order_column.desc())
    else:
        query = query.order_by(order_column.asc())

    query = query.limit(limit)

    result = await ctx.session.execute(query)
    return [row[0] for row in result.all()]


async def _execute_dry_run_single(
    recording_id: int,
    config_override: ConfigOverrideRequest | None,
    ctx: ServiceContext,
) -> dict:
    """
    Dry-run for single process endpoint.

    Shows what will be executed without actual execution.

    Args:
        recording_id: ID recording
        config_override: Override configuration
        ctx: Service context

    Returns:
        Information about steps that will be executed
    """
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(404, "Recording not found")

    # Resolve config
    resolver = ConfigResolver(ctx.session)
    processing_config = await resolver.resolve_processing_config(recording, ctx.user_id)
    output_config = await resolver.resolve_output_config(recording, ctx.user_id)

    # Define which steps will be executed
    steps = []

    # Download step
    if not recording.local_video_path:
        steps.append({"name": "download", "enabled": True})
    else:
        steps.append({"name": "download", "enabled": False, "skip_reason": "Already downloaded"})

    # Trim step
    if processing_config.get("enable_processing", True):
        steps.append({"name": "trim", "enabled": True})
    else:
        steps.append({"name": "trim", "enabled": False, "skip_reason": "Disabled in config"})

    # Transcribe step
    if processing_config.get("transcription", {}).get("enable_transcription", True):
        steps.append({"name": "transcribe", "enabled": True})
    else:
        steps.append({"name": "transcribe", "enabled": False})

    # Topics step
    steps.append({"name": "topics", "enabled": True})

    # Upload step
    auto_upload = output_config.get("auto_upload", False)
    if auto_upload:
        platforms = output_config.get("platforms", [])
        steps.append({"name": "upload", "enabled": True, "platforms": platforms})
    else:
        steps.append({"name": "upload", "enabled": False, "skip_reason": "auto_upload is false"})

    return DryRunResponse(
        dry_run=True,
        recording_id=recording_id,
        steps=steps,
    )


async def _execute_dry_run_bulk(
    recording_ids: list[int] | None,
    filters: RecordingFiltersSchema | None,
    limit: int,
    ctx: ServiceContext,
) -> BulkProcessDryRunResponse:
    """
    Dry-run for bulk process endpoint.

    Shows which recordings will be processed with checking blank_record.

    Args:
        recording_ids: Explicit list of IDs
        filters: Filters for selection
        limit: Maximum number
        ctx: Service context

    Returns:
        BulkProcessDryRunResponse with detailed information about recordings
    """
    resolved_ids = await _resolve_recording_ids(recording_ids, filters, limit, ctx)

    recording_repo = RecordingAsyncRepository(ctx.session)
    recordings_info = []
    skipped_count = 0

    for rec_id in resolved_ids:
        recording = await recording_repo.get_by_id(rec_id, ctx.user_id)

        if not recording:
            recordings_info.append(
                {"recording_id": rec_id, "will_be_processed": False, "skip_reason": "Recording not found or no access"}
            )
            skipped_count += 1
            continue

        if recording.blank_record:
            recordings_info.append(
                {
                    "recording_id": rec_id,
                    "will_be_processed": False,
                    "skip_reason": "Blank record (too short or too small)",
                }
            )
            skipped_count += 1
            continue

        recordings_info.append(
            {
                "recording_id": rec_id,
                "will_be_processed": True,
                "display_name": recording.display_name,
                "current_status": recording.status.value,
            }
        )

    return BulkProcessDryRunResponse(
        matched_count=len(resolved_ids) - skipped_count,
        skipped_count=skipped_count,
        total=len(resolved_ids),
        recordings=recordings_info,
    )


# ============================================================================
# CRUD Endpoints
# ============================================================================


@router.get("", response_model=RecordingListResponse)
async def list_recordings(
    search: str | None = Query(None, description="Search substring in display_name (case-insensitive)"),
    status_filter: str | None = Query(None, description="Filter by status"),
    failed: bool | None = Query(None, description="Only failed recordings"),
    mapped: bool | None = Query(None, description="Filter by is_mapped (true/false/null=all)"),
    include_blank: bool = Query(False, description="Include blank records (short/small)"),
    from_date: str | None = Query(None, description="Filter: start_time >= from_date (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="Filter: start_time <= to_date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Get list of recordings for user.

    Args:
        search: Search substring in display_name (case-insensitive)
        status_filter: Filter by status (INITIALIZED, DOWNLOADED, PROCESSED, etc.)
        failed: Only failed recordings
        mapped: Filter by is_mapped (true - only mapped, false - only unmapped, null - all)
        include_blank: Include blank records (default: False - hides blank records)
        from_date: Filter by start date (YYYY-MM-DD)
        to_date: Filter by end date (YYYY-MM-DD)
        page: Page number
        per_page: Number of recordings per page
        ctx: Service context

    Returns:
        List of recordings
    """
    recording_repo = RecordingAsyncRepository(ctx.session)

    # Get all recordings for user
    recordings = await recording_repo.list_by_user(ctx.user_id)

    # Apply filters
    if status_filter:
        recordings = [r for r in recordings if r.status.value == status_filter]

    if failed is not None:
        recordings = [r for r in recordings if r.failed == failed]

    if mapped is not None:
        recordings = [r for r in recordings if r.is_mapped == mapped]

    # Filter blank_record (default: hide blank records)
    if not include_blank:
        recordings = [r for r in recordings if not r.blank_record]

    # Filter by date
    if from_date:
        from utils.date_utils import parse_from_date_to_datetime

        from_dt = parse_from_date_to_datetime(from_date)
        recordings = [r for r in recordings if r.start_time >= from_dt]

    if to_date:
        from utils.date_utils import parse_to_date_to_datetime

        to_dt = parse_to_date_to_datetime(to_date)
        recordings = [r for r in recordings if r.start_time <= to_dt]

    # Filter by substring in display_name
    if search:
        search_lower = search.lower()
        recordings = [r for r in recordings if search_lower in r.display_name.lower()]

    # Pagination
    total = len(recordings)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_recordings = recordings[start:end]

    # Calculate total pages
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    items = []
    for r in paginated_recordings:
        source_info = None
        if r.source:
            source_info = SourceInfo(
                type=r.source.source_type,
                name=r.source.input_source.name if r.source.input_source else None,
                input_source_id=r.source.input_source_id,
            )

        uploads = {}
        for output in r.outputs:
            platform = output.target_type.value.lower()

            url = None
            if output.target_meta:
                url = (
                    output.target_meta.get("video_url")
                    or output.target_meta.get("target_link")
                    or output.target_meta.get("url")
                )

            uploads[platform] = UploadInfo(
                status=output.status.value.lower(),
                url=url,
                uploaded_at=output.uploaded_at,
                error=output.failed_reason if output.failed else None,
            )

        items.append(
            RecordingListItem(
                id=r.id,
                display_name=r.display_name,
                start_time=r.start_time,
                duration=r.duration,
                status=r.status,
                failed=r.failed,
                failed_at_stage=r.failed_at_stage,
                is_mapped=r.is_mapped,
                template_id=r.template_id,
                template_name=r.template.name if r.template else None,
                source=source_info,
                uploads=uploads,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )

    return RecordingListResponse(
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        items=items,
    )


@router.get("/{recording_id}")
async def get_recording(
    recording_id: int,
    detailed: bool = Query(False, description="Include detailed information (files, transcription, topics, uploads)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingListItem | DetailedRecordingResponse:
    """
    Get single recording by ID.

    Default: Returns lightweight schema (same as list view)
    With detailed=true: Returns full details with files, transcription, topics

    Args:
        recording_id: Recording ID
        detailed: If True, includes detailed information about files, transcription, topics, subtitles and uploads
        ctx: Service context

    Returns:
        RecordingListItem (default) or DetailedRecordingResponse (detailed=true)
    """
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    if not detailed:
        source_info = None
        if recording.source:
            source_info = SourceInfo(
                type=recording.source.source_type,
                name=recording.source.input_source.name if recording.source.input_source else None,
                input_source_id=recording.source.input_source_id,
            )

        uploads = {}
        for output in recording.outputs:
            platform = output.target_type.value.lower()

            url = None
            if output.target_meta:
                url = (
                    output.target_meta.get("video_url")
                    or output.target_meta.get("target_link")
                    or output.target_meta.get("url")
                )

            uploads[platform] = UploadInfo(
                status=output.status.value.lower(),
                url=url,
                uploaded_at=output.uploaded_at,
                error=output.failed_reason if output.failed else None,
            )

        return RecordingListItem(
            id=recording.id,
            display_name=recording.display_name,
            start_time=recording.start_time,
            duration=recording.duration,
            status=recording.status,
            failed=recording.failed,
            failed_at_stage=recording.failed_at_stage,
            is_mapped=recording.is_mapped,
            template_id=recording.template_id,
            template_name=recording.template.name if recording.template else None,
            source=source_info,
            uploads=uploads,
            created_at=recording.created_at,
            updated_at=recording.updated_at,
        )

    # Detailed information
    from transcription_module.manager import get_transcription_manager

    transcription_manager = get_transcription_manager()

    # Base information (common fields)
    base_data = {
        "id": recording.id,
        "display_name": recording.display_name,
        "start_time": recording.start_time,
        "duration": recording.duration,
        "status": recording.status,
        "is_mapped": recording.is_mapped,
        "blank_record": recording.blank_record,
        "processing_preferences": recording.processing_preferences,
        "source": (
            SourceResponse(
                source_type=recording.source.source_type,
                source_key=recording.source.source_key,
                metadata=recording.source.meta or {},
            )
            if recording.source
            else None
        ),
        "outputs": [
            OutputTargetResponse(
                id=output.id,
                target_type=output.target_type,
                status=output.status,
                target_meta=output.target_meta or {},
                uploaded_at=output.uploaded_at,
                failed=output.failed,
                failed_at=output.failed_at,
                failed_reason=output.failed_reason,
                retry_count=output.retry_count,
                preset=(PresetInfo(id=output.preset.id, name=output.preset.name) if output.preset else None),
            )
            for output in recording.outputs
        ],
        "failed": recording.failed,
        "failed_at": recording.failed_at,
        "failed_reason": recording.failed_reason,
        "failed_at_stage": recording.failed_at_stage,
        "video_file_size": recording.video_file_size,
        "created_at": recording.created_at,
        "updated_at": recording.updated_at,
    }

    # Video files
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

    # Audio files
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

    # Transcription (hide _metadata and model from user)
    transcription_data = None
    if transcription_manager.has_master(recording_id, user_id=ctx.user_id):
        try:
            master = transcription_manager.load_master(recording_id, user_id=ctx.user_id)
            transcription_data = {
                "exists": True,
                "created_at": master.get("created_at"),
                "language": master.get("language"),
                # Hide model from user (exists in _metadata for admin)
                "stats": master.get("stats"),
                "files": {
                    "master": str(transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "master.json"),
                    "segments_txt": str(
                        transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "cache" / "segments.txt"
                    ),
                    "words_txt": str(
                        transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "cache" / "words.txt"
                    ),
                },
            }
        except Exception as e:
            logger.warning(f"Failed to load transcription for recording {recording_id}: {e}")
            transcription_data = {"exists": False}
    else:
        transcription_data = {"exists": False}

    # Topics (all versions) - hide _metadata from user
    topics_data = None
    if transcription_manager.has_topics(recording_id, user_id=ctx.user_id):
        try:
            topics_file = transcription_manager.load_topics(recording_id, user_id=ctx.user_id)

            # Clean versions from administrative metadata
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

    # Subtitles
    subtitles = {}
    cache_dir = transcription_manager.get_dir(recording_id, user_id=ctx.user_id) / "cache"
    for fmt in ["srt", "vtt"]:
        subtitle_path = cache_dir / f"subtitles.{fmt}"
        subtitles[fmt] = {
            "path": str(subtitle_path) if subtitle_path.exists() else None,
            "exists": subtitle_path.exists(),
            "size_kb": round(subtitle_path.stat().st_size / 1024, 2) if subtitle_path.exists() else None,
        }

    # Processing stages
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

    # Upload to platforms
    uploads = {}
    if hasattr(recording, "outputs") and recording.outputs:
        for target in recording.outputs:
            platform = target.target_type.value if hasattr(target.target_type, "value") else str(target.target_type)

            # Base information
            upload_info = {
                "status": target.status.value if hasattr(target.status, "value") else str(target.status),
                "url": target.target_meta.get("video_url") or target.target_meta.get("target_link")
                if target.target_meta
                else None,
                "video_id": target.target_meta.get("video_id") if target.target_meta else None,
                "uploaded_at": target.uploaded_at.isoformat() if target.uploaded_at else None,
                "failed": target.failed,
                "retry_count": target.retry_count,
            }

            # Add information about preset if exists
            if target.preset:
                upload_info["preset"] = {
                    "id": target.preset.id,
                    "name": target.preset.name,
                }

            uploads[platform] = upload_info

    # Create response model
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


@router.post("", response_model=RecordingOperationResponse)
async def add_local_recording(
    file: UploadFile = File(...),
    display_name: str = Query(..., description="Recording name"),
    meeting_id: str | None = Query(None, description="Meeting ID (optional)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Add local video.

    Args:
        file: Video file
        display_name: Recording name
        meeting_id: Meeting ID (optional)
        ctx: Service context

    Returns:
        Created recording
    """
    # Create directory for user
    user_dir = Path(f"media/user_{ctx.user_id}/video/unprocessed")
    user_dir.mkdir(parents=True, exist_ok=True)

    # Save file
    filename = file.filename or "uploaded_video.mp4"
    file_path = user_dir / filename

    try:
        # Save file in chunks for large files
        total_size = 0
        with open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # Read 1MB at a time
                f.write(chunk)
                total_size += len(chunk)

        logger.info(f"Saved uploaded file: {file_path} ({total_size} bytes, filename: {filename})")

        # Check if file really saved
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save uploaded file",
            )

        actual_size = file_path.stat().st_size
        if actual_size != total_size:
            logger.warning(f"File size mismatch: expected {total_size}, got {actual_size}")

        logger.info(f"File verified: {file_path} exists with size {actual_size} bytes")

        # Create recording in DB
        recording_repo = RecordingAsyncRepository(ctx.session)

        from models.recording import SourceType

        # Use meeting_id or generate unique key
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
            detail=f"Failed to upload file: {e!s}",
        )


# ============================================================================
# Processing Endpoints
# ============================================================================


@router.post("/{recording_id}/download", response_model=RecordingOperationResponse)
async def download_recording(
    recording_id: int,
    force: bool = Query(False, description="Re-download if already downloaded"),
    allow_skipped: bool | None = Query(None, description="Allow processing SKIPPED recordings (default: from config)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Download recording from Zoom (async task).

    Args:
        recording_id: Recording ID
        force: Re-download if already downloaded
        allow_skipped: Allow processing SKIPPED recordings (if None - taken from config)
        ctx: Service context

    Returns:
        Task ID for checking status

    Note:
        This is an async operation. Use GET /api/v1/tasks/{task_id}
        to check status of execution.

        By default SKIPPED recordings are not downloaded. To download them you need to:
        - Explicitly pass allow_skipped=true in query parameter, OR
        - Set allow_skipped=true in user_config.processing
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

    # Get allow_skipped flag from config/parameter
    allow_skipped_resolved = await get_allow_skipped_flag(ctx.session, ctx.user_id, explicit_value=allow_skipped)

    # Check if we can download (considering SKIPPED status)
    if not should_allow_download(recording, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Download not allowed for recording with status {recording.status.value}. "
            f"SKIPPED recordings require allow_skipped=true.",
        )

    # Check if we have download_url in source metadata
    download_url = None
    if recording.source and recording.source.meta:
        download_url = recording.source.meta.get("download_url")

    if not download_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No download URL available for this recording. Please sync from Zoom first.",
        )

    # Check if not already downloaded
    if not force and recording.status == ProcessingStatus.DOWNLOADED and recording.local_video_path:
        if Path(recording.local_video_path).exists():
            return {
                "success": True,
                "message": "Recording already downloaded",
                "recording_id": recording_id,
                "local_video_path": recording.local_video_path,
                "task_id": None,
            }

    # Start async task
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


@router.post("/{recording_id}/trim", response_model=RecordingOperationResponse)
async def trim_recording(
    recording_id: int,
    config: TrimVideoRequest = TrimVideoRequest(),
    allow_skipped: bool | None = Query(None, description="Allow processing SKIPPED recordings (default: from config)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Trim video (FFmpeg - remove silence) - async task.

    Args:
        recording_id: Recording ID
        config: Processing configuration
        allow_skipped: Allow processing SKIPPED recordings (if None - taken from config)
        ctx: Service context

    Returns:
        Task ID for checking status of execution

    Note:
        This is an async operation. Use GET /api/v1/tasks/{task_id}
        to check the status of execution.

        By default, SKIPPED recordings are not processed. To process them, you need to:
        - Explicitly pass allow_skipped=true in the query parameter, OR
        - Set allow_skipped=true in user_config.processing
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_processing
    from api.tasks.processing import trim_video_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Get allow_skipped flag from config/parameter
    allow_skipped_resolved = await get_allow_skipped_flag(ctx.session, ctx.user_id, explicit_value=allow_skipped)

    # Check if we can process (considering SKIPPED status)
    if not should_allow_processing(recording, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Processing not allowed for recording with status {recording.status.value}. "
            f"SKIPPED recordings require allow_skipped=true.",
        )

    # Check if original video is present
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

    # Build manual override from config
    manual_override = {
        "processing": {
            "silence_threshold": config.silence_threshold,
            "min_silence_duration": config.min_silence_duration,
            "padding_before": config.padding_before,
            "padding_after": config.padding_after,
        }
    }

    # Start async task
    task = trim_video_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        manual_override=manual_override,
    )

    logger.info(f"Trim task {task.id} created for recording {recording_id}, user {ctx.user_id}")

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Processing task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.post("/bulk/process")
async def bulk_process_recordings(
    data: BulkProcessRequest,
    dry_run: bool = Query(False, description="Dry-run: show which recordings will be processed"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse | BulkProcessDryRunResponse:
    """
    Bulk processing of multiple recordings (async tasks) - full pipeline.

    Supports two modes of selection:
    1. Explicit list of recording_ids
    2. Automatic selection by filters (template_id, status, is_mapped, etc.)

    Dry-run mode:
    - dry_run=true: Show which recordings will be processed without actual execution
    - Useful for checking filters before bulk processing

    Args:
        data: BulkProcessRequest with recording_ids or filters + configuration override
        dry_run: Dry-run mode (only checking, without execution)
        ctx: Service context

    Returns:
        List of task_id for each recording or dry-run information

    Note:
        Each recording is processed in a separate task.
        Use GET /api/v1/tasks/{task_id} to check the status of each task.
    """

    # Handle dry-run mode
    if dry_run:
        return await _execute_dry_run_bulk(data.recording_ids, data.filters, data.limit, ctx)

    from api.tasks.processing import process_recording_task

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    # Build manual override from config_override
    manual_override = {}
    if data.processing_config:
        manual_override["processing_config"] = data.processing_config
    if data.metadata_config:
        manual_override["metadata_config"] = data.metadata_config
    if data.output_config:
        manual_override["output_config"] = data.output_config

    for recording_id in recording_ids:
        try:
            # Check if recording exists
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

            if not recording:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "error",
                        "error": "Recording not found or no access",
                        "task_id": None,
                    }
                )
                continue

            # Skip blank records
            if recording.blank_record:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "skipped",
                        "error": "Blank record (too short or too small)",
                        "task_id": None,
                    }
                )
                continue

            # Start task for this recording (template-driven + manual override)
            task = process_recording_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                manual_override=manual_override if manual_override else None,
            )

            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                    "check_status_url": f"/api/v1/tasks/{task.id}",
                }
            )

            logger.info(f"Batch task {task.id} created for recording {recording_id}, user {ctx.user_id}")

        except Exception as e:
            logger.error(f"Failed to create task for recording {recording_id}: {e}")
            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "error",
                    "error": str(e),
                    "task_id": None,
                }
            )

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    skipped_count = len([t for t in tasks if t["status"] == "skipped"])

    return RecordingBulkOperationResponse(
        total=len(recording_ids),
        queued_count=queued_count,
        skipped_count=skipped_count,
        tasks=tasks,
    )


@router.post("/{recording_id}/process", response_model=RecordingOperationResponse)
async def process_recording(
    recording_id: int,
    config: ConfigOverrideRequest = ConfigOverrideRequest(),
    dry_run: bool = Query(False, description="Dry-run: show what will be done without actual execution"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse | DryRunResponse:
    """
    Full processing pipeline (async task): download → trim → transcribe → topics → upload.

    Supports flexible config overrides:
    - processing_config: Override processing settings (transcription, silence detection, etc.)
    - metadata_config: Override metadata (title, description, playlists, albums, etc.)
    - output_config: Override output settings (preset_ids, auto_upload, etc.)

    Dry-run mode:
    - dry_run=true: Show which steps will be done without actual execution
    - Useful for checking configuration before actual processing

    Args:
        recording_id: Recording ID
        config: Flexible overrides for configuration (optional)
        dry_run: Dry-run mode (only checking, without execution)
        ctx: Service context

    Returns:
        Task ID for checking status of execution

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
        This is an async operation, performing all steps sequentially.
        Use GET /api/v1/tasks/{task_id} to check progress.
    """
    # Handle dry-run mode
    if dry_run:
        return await _execute_dry_run_single(recording_id, config, ctx)

    from api.tasks.processing import process_recording_task

    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Build manual override from flexible config
    manual_override = _build_override_from_flexible(config)

    task = process_recording_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        manual_override=manual_override,
    )

    logger.info(
        f"Process recording task {task.id} created for recording {recording_id}, user {ctx.user_id}, "
        f"overrides: {list(manual_override.keys())}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Processing task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
        "config_overrides": manual_override if manual_override else None,
    }


@router.post("/{recording_id}/transcribe", response_model=RecordingOperationResponse)
async def transcribe_recording(
    recording_id: int,
    use_batch_api: bool = Query(False, description="Use Batch API (cheaper, but requires polling)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Transcribe recording (async task) with ADMIN credentials.

    ⚠️ IMPORTANT: Creates only master.json (words, segments).
    For topic extraction, use separate endpoint /topics.

    Args:
        recording_id: Recording ID
        use_batch_api: Use Batch API (cheaper ~50%, but longer waiting)
        ctx: Service context with user_id and session

    Returns:
        Task ID for checking status of execution

    Note:
        Uses ADMIN credentials for transcription through Fireworks API.

        Batch API (use_batch_api=true):
        - Cheaper ~50% than synchronous API
        - Requires polling to get result
        - Waiting time: usually several minutes
        - Documentation: https://docs.fireworks.ai/api-reference/create-batch-request

        This is an async operation. Use GET /api/v1/tasks/{task_id}
        to check status of execution and get results.
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_transcription
    from api.tasks.processing import batch_transcribe_recording_task, transcribe_recording_task

    # Get recording from DB
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Recording {recording_id} not found or you don't have access"
        )

    # Get allow_skipped flag from config (for transcription you can add query param if needed)
    allow_skipped_resolved = await get_allow_skipped_flag(ctx.session, ctx.user_id)

    # Check if transcription can be started (using FSM logic)
    if not should_allow_transcription(recording, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transcription cannot be started. Current status: {recording.status.value}. "
            f"Transcription is already completed or in progress. "
            f"SKIPPED recordings require allow_skipped=true in config.",
        )

    # Check if file for processing exists
    if not recording.processed_video_path and not recording.local_video_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No video file available for transcription. Please download the recording first.",
        )

    audio_path = recording.processed_video_path or recording.local_video_path

    # Check if file exists
    if not Path(audio_path).exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Video file not found at path: {audio_path}"
        )

    # Select mode: Batch API or synchronous API
    if use_batch_api:
        # Batch API mode: submit batch job, then polling
        from fireworks_module import FireworksConfig, FireworksTranscriptionService

        fireworks_config = FireworksConfig.from_file("config/fireworks_creds.json")

        # Check if account_id exists
        if not fireworks_config.account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Batch API is not available: account_id is not configured in config/fireworks_creds.json. "
                "Add account_id from Fireworks dashboard or use use_batch_api=false.",
            )

        fireworks_service = FireworksTranscriptionService(fireworks_config)

        # Submit batch job
        try:
            batch_result = await fireworks_service.submit_batch_transcription(
                audio_path=audio_path,
                language=fireworks_config.language,
                prompt=None,  # TODO: add prompt from config
            )
            batch_id = batch_result.get("batch_id")

            if not batch_id:
                raise ValueError("Batch API did not return batch_id")

            logger.info(
                f"Batch transcription submitted | batch_id={batch_id} | recording={recording_id} | user={ctx.user_id}"
            )

            # Start polling task
            task = batch_transcribe_recording_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                batch_id=batch_id,
                poll_interval=10.0,  # 10 seconds
                max_wait_time=3600.0,  # 1 hour
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
                detail=f"Failed to submit batch transcription: {e!s}",
            )
    else:
        # Synchronous API mode
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


@router.post("/{recording_id}/upload/{platform}", response_model=RecordingOperationResponse)
async def upload_recording(
    recording_id: int,
    platform: str,
    preset_id: int | None = None,
    allow_skipped: bool | None = Query(None, description="Allow upload of SKIPPED recordings (default: from config)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Upload recording to platform (async task) with user credentials.

    Args:
        recording_id: Recording ID
        platform: Platform (youtube, vk)
        preset_id: ID output preset (optional)
        allow_skipped: Allow upload of SKIPPED recordings (if None - from config)
        ctx: Service context

    Returns:
        Task ID for checking status of execution

    Note:
        This is an async operation. Use GET /api/v1/tasks/{task_id}
        to check status of execution and get results.

        By default SKIPPED recordings are not uploaded. To upload them you need to:
        - Explicitly pass allow_skipped=true in query parameter, OR
        - Set allow_skipped=true in user_config.processing, OR
        - Set allow_skipped=true in template.output_config
    """
    from api.helpers.config_resolver import get_allow_skipped_flag
    from api.helpers.status_manager import should_allow_upload
    from api.tasks.upload import upload_recording_to_platform
    from models.recording import TargetType

    # Get recording from DB
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Recording {recording_id} not found or you don't have access"
        )

    # Get allow_skipped flag from config/parameter
    allow_skipped_resolved = await get_allow_skipped_flag(ctx.session, ctx.user_id, explicit_value=allow_skipped)

    # Check if upload can be started to this platform (using FSM logic)
    try:
        target_type_enum = TargetType[platform.upper()]
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid platform: {platform}. Supported: youtube, vk, etc.",
        )

    if not should_allow_upload(recording, target_type_enum.value, allow_skipped=allow_skipped_resolved):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload to {platform} cannot be started. Current status: {recording.status.value}. "
            f"Either upload is already completed/in progress, or recording is not ready for upload. "
            f"SKIPPED recordings require allow_skipped=true.",
        )

    # Check if processed video exists
    if not recording.processed_video_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No processed video available. Please process the recording first.",
        )

    video_path = recording.processed_video_path

    # Check if file exists
    if not Path(video_path).exists():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Processed video file not found at path: {video_path}"
        )

    # Start async task
    task = upload_recording_to_platform.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        platform=platform,
        preset_id=preset_id,
    )

    logger.info(f"Upload task {task.id} created for recording {recording_id} to {platform}, user {ctx.user_id}")

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


@router.post("/{recording_id}/topics", response_model=RecordingOperationResponse)
async def extract_topics(
    recording_id: int,
    granularity: str = Query("long", description="Mode: 'short' or 'long'"),
    version_id: str | None = Query(None, description="Version ID (optional)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Extract topics from existing transcription (async task).

    ⚠️ IMPORTANT: Requires existing transcription. Run /transcribe first.
    ✨ Can be run multiple times with different settings to create different versions.

    Args:
        recording_id: Recording ID
        granularity: Extraction mode ('short' - large topics | 'long' - detailed)
        version_id: Version ID (if not specified, generated automatically)
        ctx: Service context

    Returns:
        Task ID for checking status of execution

    Note:
        Topic extraction model is selected automatically (with retries and fallbacks).
        Uses ADMIN credentials for topic extraction.
        This is an async operation. Use GET /api/v1/tasks/{task_id}
        to check status of execution.
    """
    from api.tasks.processing import extract_topics_task

    # Get recording from DB
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Check if transcription exists
    from transcription_module.manager import get_transcription_manager

    transcription_manager = get_transcription_manager()
    if not transcription_manager.has_master(recording_id, user_id=ctx.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcription found. Please run /transcribe first.",
        )

    # Start async task
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


@router.post("/{recording_id}/subtitles", response_model=RecordingOperationResponse)
async def generate_subtitles(
    recording_id: int,
    formats: list[str] = Query(["srt", "vtt"], description="Formats: 'srt', 'vtt'"),
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingOperationResponse:
    """
    Generate subtitles from transcription (async task).

    ⚠️ IMPORTANT: Requires transcription. Run /transcribe first.

    Args:
        recording_id: ID recording
        formats: List of subtitle formats ['srt', 'vtt']
        ctx: Service context

    Returns:
        Task ID for checking status

    Note:
        This is an async operation. Use GET /api/v1/tasks/{task_id}
        to check the status of execution.
    """
    from api.tasks.processing import generate_subtitles_task

    # Get recording from DB
    recording_repo = RecordingAsyncRepository(ctx.session)
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

    if not recording:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording {recording_id} not found or you don't have access",
        )

    # Check if transcription is present
    from transcription_module.manager import get_transcription_manager

    transcription_manager = get_transcription_manager()
    if not transcription_manager.has_master(recording_id, user_id=ctx.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcription found. Please run /transcribe first.",
        )

    # Start async task
    task = generate_subtitles_task.delay(
        recording_id=recording_id,
        user_id=ctx.user_id,
        formats=formats,
    )

    logger.info(
        f"Generate subtitles task {task.id} created for recording {recording_id}, user {ctx.user_id}, formats={formats}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "recording_id": recording_id,
        "status": "queued",
        "message": "Subtitle generation task has been queued",
        "check_status_url": f"/api/v1/tasks/{task.id}",
    }


@router.post("/bulk/transcribe", response_model=RecordingBulkOperationResponse)
async def bulk_transcribe_recordings(
    data: BulkTranscribeRequest,
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse:
    """
    Bulk transcription of multiple recordings (async tasks).

    Supports two modes of selection:
    1. Explicit list of recording_ids
    2. Automatic selection by filters (template_id, status, is_mapped, etc.)

    ⚠️ IMPORTANT: Uses ADMIN credentials for transcription.
    Creates only master.json for each recording.
    For topic extraction, use /topics after transcription.
    Support for Fireworks Batch API:
    - use_batch_api=true: Cheaper, but longer (polling every 10 seconds)
    - use_batch_api=false: Regular sync API (default)

    Args:
        data: Bulk transcription request (recording_ids or filters + parameters)
        ctx: Service context

    Returns:
        List of task_id for each recording

    Note:
        Each recording is transcribed in a separate task.
        Use GET /api/v1/tasks/{task_id} to check the status of each task.
    """
    from api.tasks.processing import batch_transcribe_recording_task, transcribe_recording_task

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    if not recording_ids:
        return {
            "queued_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "tasks": [],
            "message": "No recordings matched the criteria",
        }

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            # Check if recording exists
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)

            if not recording:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "error",
                        "error": "Recording not found or no access",
                        "task_id": None,
                    }
                )
                continue

            # Skip blank records
            if recording.blank_record:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "skipped",
                        "reason": "Blank record (too short or too small)",
                        "task_id": None,
                    }
                )
                continue

            # Check if file is present
            if not recording.processed_video_path and not recording.local_video_path:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "error",
                        "error": "No video file available",
                        "task_id": None,
                    }
                )
                continue

            # Select mode: Batch API or regular sync API
            if data.use_batch_api:
                # Fireworks Batch API mode
                task = batch_transcribe_recording_task.delay(
                    recording_id=recording_id,
                    user_id=ctx.user_id,
                    batch_id=None,  # Will be set by task
                    poll_interval=data.poll_interval,
                    max_wait_time=data.max_wait_time,
                )
                task_info = {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                    "mode": "batch_api",
                    "check_status_url": f"/api/v1/tasks/{task.id}",
                }
            else:
                # Sync API mode
                task = transcribe_recording_task.delay(
                    recording_id=recording_id,
                    user_id=ctx.user_id,
                )
                task_info = {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                    "mode": "sync_api",
                    "check_status_url": f"/api/v1/tasks/{task.id}",
                }

            tasks.append(task_info)

            logger.info(
                f"Bulk transcribe task {task.id} created for recording {recording_id}, user {ctx.user_id}, mode={task_info['mode']}"
            )

        except Exception as e:
            logger.error(f"Failed to create transcribe task for recording {recording_id}: {e}")
            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "error",
                    "error": str(e),
                    "task_id": None,
                }
            )

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    skipped_count = len([t for t in tasks if t["status"] == "skipped"])
    error_count = len([t for t in tasks if t["status"] == "error"])

    return {
        "queued_count": queued_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "mode": "batch_api" if data.use_batch_api else "sync_api",
        "tasks": tasks,
    }


@router.post("/{recording_id}/retry-upload", response_model=RetryUploadResponse)
async def retry_failed_uploads(
    recording_id: int,
    platforms: list[str] | None = None,
    ctx: ServiceContext = Depends(get_service_context),
) -> RetryUploadResponse:
    """
    Retry upload for failed output_targets.

    If platforms are not specified: retry all with status=FAILED
    If platforms are specified: retry only these platforms
    Uses actual preset_id from output_target

    Args:
        recording_id: ID recording
        platforms: List of platforms for retry (optional)
        ctx: Service context

    Returns:
        List of tasks for retry upload
    """
    from api.tasks.upload import upload_recording_to_platform

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Get recording from DB
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Get failed output_targets
    failed_targets = []
    for output in recording.outputs:
        if output.failed or output.status == TargetStatus.FAILED.value:
            # If specific platforms are specified, filter them
            if platforms:
                if output.target_type.value.lower() in [p.lower() for p in platforms]:
                    failed_targets.append(output)
            else:
                failed_targets.append(output)

    if not failed_targets:
        return {
            "message": "No failed uploads found for retry",
            "recording_id": recording_id,
            "tasks": [],
        }

    # Start retry for each failed target
    tasks = []
    for target in failed_targets:
        try:
            task = upload_recording_to_platform.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                platform=target.target_type.value.lower(),
                preset_id=target.preset_id,
            )

            tasks.append(
                {
                    "platform": target.target_type.value,
                    "task_id": str(task.id),
                    "status": "queued",
                    "previous_attempts": target.retry_count,
                }
            )

            logger.info(
                f"Queued retry upload for recording {recording_id} to {target.target_type.value} "
                f"(attempt {target.retry_count + 1})"
            )

        except Exception as e:
            logger.error(f"Failed to queue retry for {target.target_type.value}: {e}")
            tasks.append(
                {
                    "platform": target.target_type.value,
                    "status": "error",
                    "error": str(e),
                }
            )

    return RetryUploadResponse(
        message=f"Retry queued for {len([t for t in tasks if t['status'] == 'queued'])} platforms",
        recording_id=recording_id,
        tasks=tasks,
    )


@router.get("/{recording_id}/config")
async def get_recording_config(
    recording_id: int,
    ctx: ServiceContext = Depends(get_service_context),
):
    """
    Get current resolved configuration for editing recording.

    Returns:
    - processing_config: resolved config (user + template if exists)
    - output_config: preset_ids for platforms
    - metadata_config: metadata templates (title, description, tags)
    - has_manual_override: bool - if there is a saved manual config
    - template_name: name of template if attached

    NOTE: Metadata (title, description, tags) is configured in output_preset.preset_metadata,
    not in recording config.

    Args:
        recording_id: ID recording
        ctx: Service context

    Returns:
        Resolved configuration for editing
    """
    from api.schemas.recording.operations import RecordingConfigResponse
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Get recording from DB
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Resolve configuration
    config_resolver = ConfigResolver(ctx.session)
    config_data = await config_resolver.get_base_config_for_edit(recording, ctx.user_id)

    return RecordingConfigResponse(
        recording_id=recording_id,
        is_mapped=recording.is_mapped,
        template_id=config_data["template_id"],
        template_name=config_data["template_name"],
        has_manual_override=config_data["has_manual_override"],
        processing_config=config_data["processing_config"],
        output_config=config_data["output_config"],
        metadata_config=config_data["metadata_config"],
    )


@router.put("/{recording_id}/config")
async def update_recording_config(
    recording_id: int,
    processing_config: dict | None = None,
    output_config: dict | None = None,
    ctx: ServiceContext = Depends(get_service_context),
) -> dict:
    """
    Save user overrides in recording.processing_preferences.

    Logic:
    1. Get current resolved config (base from template)
    2. Apply changes from request
    3. Save only overrides in recording.processing_preferences

    Now this recording will use template config + user overrides.

    NOTE: Metadata (title, description, tags) is configured in output_preset.preset_metadata,
    not here.

    Args:
        recording_id: Recording ID
        processing_config: Configuration of processing (optional)
        output_config: Configuration of output presets (optional)
        ctx: Service context

    Returns:
        Updated configuration
    """
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Get recording from DB
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
            new_preferences.get("processing_config", {}), processing_config
        )

    if output_config is not None:
        if "output_config" not in new_preferences:
            new_preferences["output_config"] = {}
        new_preferences["output_config"] = config_resolver._merge_configs(
            new_preferences.get("output_config", {}), output_config
        )

    # Save overrides to recording.processing_preferences
    recording.processing_preferences = new_preferences if new_preferences else None
    await ctx.session.commit()

    logger.info(f"Updated manual config for recording {recording_id}")

    # Get effective config after update
    effective_config = await config_resolver.resolve_processing_config(recording, ctx.user_id)

    from api.schemas.recording.operations import ConfigUpdateResponse

    return ConfigUpdateResponse(
        recording_id=recording_id,
        message="Configuration saved",
        has_manual_override=bool(new_preferences),
        overrides=new_preferences,
        effective_config=effective_config,
    )


@router.delete("/{recording_id}/config", response_model=ConfigSaveResponse)
async def reset_to_template(
    recording_id: int,
    ctx: ServiceContext = Depends(get_service_context),
) -> ConfigSaveResponse:
    """
    Reset user settings and return to template.

    Clears recording.processing_preferences, after which the recording will
    use only the configuration from the template.

    Args:
        recording_id: ID recording
        ctx: Service context

    Returns:
        Updated configuration
    """
    from api.services.config_resolver import ConfigResolver

    recording_repo = RecordingAsyncRepository(ctx.session)

    # Get recording from DB
    recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
    if not recording:
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")

    # Clear overrides
    recording.processing_preferences = None
    await ctx.session.commit()

    # Get effective config (from template)
    config_resolver = ConfigResolver(ctx.session)
    effective_config = await config_resolver.resolve_processing_config(recording, ctx.user_id)

    logger.info(f"Reset recording {recording_id} to template configuration")

    return ConfigSaveResponse(
        recording_id=recording_id,
        message="Reset to template configuration",
        has_manual_override=False,
        effective_config=effective_config,
    )


@router.post("/{recording_id}/reset", response_model=ResetRecordingResponse)
async def reset_recording(
    recording_id: int,
    delete_files: bool = Query(True, description="Delete all files (video, audio, transcription)"),
    ctx: ServiceContext = Depends(get_service_context),
) -> ResetRecordingResponse:
    """
    Reset recording to initial state.

    What does:
    - Deletes all processed files (video, audio, transcription, subtitles)
    - Clears metadata (topics, transcription_info)
    - Deletes output_targets
    - Deletes processing_stages
    - Returns status to INITIALIZED
    - Clears failed flag and failed_reason

    Optional:
    - local_video_path (downloaded video) - if delete_files=False
    - template_id, is_mapped
    - processing_preferences (manual config)

    Args:
        recording_id: Recording ID
        delete_files: Delete all files (default: True)
        ctx: Service context

    Returns:
        Result of reset operation
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
                # Delete file and its parent directory if it is empty
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
    await ctx.session.execute(delete(OutputTargetModel).where(OutputTargetModel.recording_id == recording_id))

    # Delete processing_stages
    await ctx.session.execute(delete(ProcessingStageModel).where(ProcessingStageModel.recording_id == recording_id))

    await ctx.session.commit()

    logger.info(
        f"Reset recording {recording_id}: deleted {len(deleted_files)} files, "
        f"{len(errors)} errors, status -> INITIALIZED"
    )

    return ResetRecordingResponse(
        success=True,
        recording_id=recording_id,
        message="Recording reset to initial state",
        deleted_files=deleted_files if deleted_files else None,
        errors=errors if errors else None,
        status="INITIALIZED",
        preserved={
            "template_id": recording.template_id,
            "is_mapped": recording.is_mapped,
            "processing_preferences": bool(recording.processing_preferences),
        },
        task_id=None,
    )


# ============================================================================
# New Bulk Operations Endpoints
# ============================================================================


@router.post("/bulk/download", response_model=RecordingBulkOperationResponse)
async def bulk_download_recordings(
    data: BulkDownloadRequest,
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse:
    """
    Bulk download recordings from Zoom.

    Supports recording_ids or filters for automatic selection.
    """
    from api.tasks.processing import download_recording_task

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            if not recording:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "error",
                        "error": "Recording not found",
                        "task_id": None,
                    }
                )
                continue

            if recording.blank_record:
                tasks.append(
                    {
                        "recording_id": recording_id,
                        "status": "skipped",
                        "error": "Blank record",
                        "task_id": None,
                    }
                )
                continue

            task = download_recording_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                force=data.force,
                manual_override=None,
            )

            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                    "check_status_url": f"/api/v1/tasks/{task.id}",
                }
            )

            logger.info(f"Bulk download task {task.id} for recording {recording_id}, user {ctx.user_id}")

        except Exception as e:
            logger.error(f"Failed to queue download for recording {recording_id}: {e}")
            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "error",
                    "error": str(e),
                    "task_id": None,
                }
            )

    queued_count = len([t for t in tasks if t["status"] == "queued"])

    return RecordingBulkOperationResponse(
        queued_count=queued_count,
        skipped_count=len([t for t in tasks if t["status"] == "skipped"]),
        tasks=tasks,
    )


@router.post("/bulk/trim", response_model=RecordingBulkOperationResponse)
async def bulk_trim_recordings(
    data: BulkTrimRequest,
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse:
    """
    Bulk processing video - removing silence (FFmpeg).

    Supports recording_ids or filters for automatic selection.
    """
    from api.tasks.processing import trim_video_task

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    # Build manual override
    manual_override = {
        "processing": {
            "silence_threshold": data.silence_threshold,
            "min_silence_duration": data.min_silence_duration,
            "padding_before": data.padding_before,
            "padding_after": data.padding_after,
        }
    }

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            if not recording or recording.blank_record:
                continue

            task = trim_video_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                manual_override=manual_override,
            )

            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                }
            )

        except Exception as e:
            logger.error(f"Failed to queue trim for recording {recording_id}: {e}")

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    skipped_count = len([t for t in tasks if t["status"] == "skipped"])

    return {
        "queued_count": queued_count,
        "skipped_count": skipped_count,
        "tasks": tasks,
    }


@router.post("/bulk/topics", response_model=RecordingBulkOperationResponse)
async def bulk_extract_topics(
    data: BulkTopicsRequest,
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse:
    """
    Bulk extraction topics from transcriptions.

    Supports recording_ids or filters for automatic selection.
    """
    from api.tasks.processing import extract_topics_task

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            if not recording or recording.blank_record:
                continue

            task = extract_topics_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
                granularity=data.granularity,
                version_id=data.version_id,
            )

            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                }
            )

        except Exception as e:
            logger.error(f"Failed to queue topics for recording {recording_id}: {e}")

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    skipped_count = len([t for t in tasks if t["status"] == "skipped"])

    return {
        "queued_count": queued_count,
        "skipped_count": skipped_count,
        "tasks": tasks,
    }


@router.post("/bulk/subtitles", response_model=RecordingBulkOperationResponse)
async def bulk_generate_subtitles(
    data: BulkSubtitlesRequest,
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse:
    """
    Bulk generation subtitles.

    Supports recording_ids or filters for automatic selection.
    """
    from api.tasks.processing import generate_subtitles_task

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            if not recording or recording.blank_record:
                continue

            task = generate_subtitles_task.delay(
                recording_id=recording_id,
                user_id=ctx.user_id,
            )

            tasks.append(
                {
                    "recording_id": recording_id,
                    "status": "queued",
                    "task_id": task.id,
                }
            )

        except Exception as e:
            logger.error(f"Failed to queue subtitles for recording {recording_id}: {e}")

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    skipped_count = len([t for t in tasks if t["status"] == "skipped"])

    return {
        "queued_count": queued_count,
        "skipped_count": skipped_count,
        "tasks": tasks,
    }


@router.post("/bulk/upload", response_model=RecordingBulkOperationResponse)
async def bulk_upload_recordings(
    data: BulkUploadRequest,
    ctx: ServiceContext = Depends(get_service_context),
) -> RecordingBulkOperationResponse:
    """
    Bulk upload recordings to platforms.

    Supports recording_ids or filters for automatic selection.
    """
    from api.tasks.upload import upload_recording_to_platform

    # Resolve recording IDs
    recording_ids = await _resolve_recording_ids(data.recording_ids, data.filters, data.limit, ctx)

    recording_repo = RecordingAsyncRepository(ctx.session)
    tasks = []

    for recording_id in recording_ids:
        try:
            recording = await recording_repo.get_by_id(recording_id, ctx.user_id)
            if not recording or recording.blank_record:
                continue

            platforms = data.platforms if data.platforms else ["youtube", "vk"]

            for platform in platforms:
                # Use preset_id from request, or let upload task auto-select from template
                # (auto-select logic is in upload_recording_to_platform task)
                task = upload_recording_to_platform.delay(
                    recording_id=recording_id,
                    user_id=ctx.user_id,
                    platform=platform,
                    preset_id=data.preset_id,  # Can be None - task will auto-select from template
                )

                tasks.append(
                    {
                        "recording_id": recording_id,
                        "platform": platform,
                        "status": "queued",
                        "task_id": task.id,
                    }
                )

        except Exception as e:
            logger.error(f"Failed to queue upload for recording {recording_id}: {e}")

    queued_count = len([t for t in tasks if t["status"] == "queued"])
    skipped_count = len([t for t in tasks if t["status"] == "skipped"])

    return {
        "queued_count": queued_count,
        "skipped_count": skipped_count,
        "tasks": tasks,
    }
