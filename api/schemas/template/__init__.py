"""Template, config, source and preset schemas (fully typed)"""

from .config import BaseConfigCreate, BaseConfigResponse, BaseConfigUpdate
from .input_source import (
    BatchSyncResponse,
    BulkSyncRequest,
    InputSourceCreate,
    InputSourceResponse,
    InputSourceUpdate,
    SourceSyncResult,
)
from .matching_rules import MatchingRules
from .metadata_config import TemplateMetadataConfig, VKMetadataConfig, YouTubeMetadataConfig
from .operations import BulkDeleteResponse, RematchTaskResponse
from .output_config import TemplateOutputConfig
from .output_preset import OutputPresetCreate, OutputPresetResponse, OutputPresetUpdate
from .preset_metadata import (
    TopicsDisplayConfig,
    TopicsDisplayFormat,
    VKPresetMetadata,
    VKPrivacyLevel,
    YouTubeLicense,
    YouTubePresetMetadata,
    YouTubePrivacy,
)
from .processing_config import TemplateProcessingConfig, TranscriptionProcessingConfig
from .source_config import (
    GoogleDriveSourceConfig,
    LocalFileSourceConfig,
    SourceConfig,
    YandexDiskSourceConfig,
    ZoomSourceConfig,
)
from .sync import SyncSourceResponse, SyncTaskResponse
from .template import (
    RecordingTemplateCreate,
    RecordingTemplateListResponse,
    RecordingTemplateResponse,
    RecordingTemplateUpdate,
)

__all__ = [
    # Base configs
    "BaseConfigCreate",
    "BaseConfigResponse",
    "BaseConfigUpdate",
    "BatchSyncResponse",
    # ===== OPERATIONS =====
    "BulkDeleteResponse",
    "BulkSyncRequest",
    "GoogleDriveSourceConfig",
    # ===== INPUT SOURCES (typed) =====
    "InputSourceCreate",
    "InputSourceResponse",
    "InputSourceUpdate",
    "LocalFileSourceConfig",
    # ===== NESTED TYPED MODELS =====
    # Matching Rules
    "MatchingRules",
    # ===== OUTPUT PRESETS (typed) =====
    "OutputPresetCreate",
    "OutputPresetResponse",
    "OutputPresetUpdate",
    # ===== RECORDING TEMPLATES (typed) =====
    "RecordingTemplateCreate",
    "RecordingTemplateListResponse",
    "RecordingTemplateResponse",
    "RecordingTemplateUpdate",
    "RematchTaskResponse",
    # Source Config (typed)
    "SourceConfig",
    "SourceSyncResult",
    "SyncSourceResponse",
    "SyncTaskResponse",
    # Metadata Config
    "TemplateMetadataConfig",
    # Output Config
    "TemplateOutputConfig",
    # Processing Config
    "TemplateProcessingConfig",
    # ===== COMPONENTS =====
    "TopicsDisplayConfig",
    # ===== ENUMS =====
    "TopicsDisplayFormat",
    "TranscriptionProcessingConfig",
    "VKMetadataConfig",
    "VKPresetMetadata",
    "VKPrivacyLevel",
    "YandexDiskSourceConfig",
    "YouTubeLicense",
    "YouTubeMetadataConfig",
    # Preset Metadata (typed)
    "YouTubePresetMetadata",
    "YouTubePrivacy",
    "ZoomSourceConfig",
]
