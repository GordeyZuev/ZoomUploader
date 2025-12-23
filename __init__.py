from .api import ZoomAPI
from .config import ZoomConfig, get_config_by_account, load_config_from_file
from .database import DatabaseConfig, DatabaseManager, RecordingModel
from .logger import get_logger, setup_logger
from .models import (
    MeetingRecording,
    OutputTarget,
    ProcessingStatus,
    SourceType,
    TargetStatus,
    TargetType,
)
from .utils import (
    export_recordings_summary,
    filter_ready_for_processing,
    filter_ready_for_upload,
    filter_recordings_by_duration,
    format_date,
    format_duration,
    format_file_size,
    get_recordings_by_date_range,
    get_recordings_statistics,
    process_meetings_data,
    save_recordings_to_csv,
    save_recordings_to_json,
)

# Импорты модулей обработки и загрузки
from .video_processing_module import (
    ProcessingConfig,
    SegmentProcessor,
    VideoProcessor,
    VideoSegment,
)
from .video_upload_module import (
    UploadConfig,
    UploadManager,
    VKConfig,
    VKUploader,
    YouTubeConfig,
    YouTubeUploader,
)

__version__ = "1.0.0"
__author__ = "Video Processing Pipeline Team"

__all__ = [
    # Core Models
    'MeetingRecording',
    'ProcessingStatus',
    'SourceType',
    'TargetType',
    'TargetStatus',
    'OutputTarget',
    # API
    'ZoomAPI',
    # Config
    'ZoomConfig',
    'load_config_from_file',
    'get_config_by_account',
    # Logger
    'get_logger',
    'setup_logger',
    # Database
    'DatabaseManager',
    'DatabaseConfig',
    'RecordingModel',
    # Video Processing
    'VideoProcessor',
    'ProcessingConfig',
    'VideoSegment',
    'SegmentProcessor',
    # Video Upload
    'UploadManager',
    'UploadConfig',
    'YouTubeUploader',
    'YouTubeConfig',
    'VKUploader',
    'VKConfig',
    # Utils
    'process_meetings_data',
    'filter_recordings_by_duration',
    'filter_ready_for_processing',
    'filter_ready_for_upload',
    'get_recordings_statistics',
    'get_recordings_by_date_range',
    'save_recordings_to_json',
    'save_recordings_to_csv',
    'export_recordings_summary',
    'format_date',
    'format_duration',
    'format_file_size',
]
