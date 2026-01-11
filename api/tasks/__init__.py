"""Асинхронные задачи Celery."""

# Import all tasks so Celery can discover them
from .automation import run_automation_job_task  # noqa: F401
from .maintenance import cleanup_expired_tokens_task  # noqa: F401
from .processing import (  # noqa: F401
    download_recording_task,
    extract_topics_task,
    full_pipeline_task,
    generate_subtitles_task,
    process_video_task,
    transcribe_recording_task,
)
from .sync_tasks import batch_sync_sources_task, sync_single_source_task  # noqa: F401
from .upload import batch_upload_recordings, upload_recording_to_platform  # noqa: F401
