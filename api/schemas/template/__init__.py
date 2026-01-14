"""Схемы для шаблонов, конфигураций, источников и пресетов (полностью типизированные)."""

from .config import BaseConfigCreate, BaseConfigResponse, BaseConfigUpdate
from .input_source import (
    BatchSyncRequest,
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
    "BaseConfigUpdate",
    "BaseConfigResponse",
    # ===== INPUT SOURCES (typed) =====
    "InputSourceCreate",
    "InputSourceUpdate",
    "InputSourceResponse",
    "BulkSyncRequest",
    "BatchSyncRequest",
    "BatchSyncResponse",
    "SourceSyncResult",
    # ===== OUTPUT PRESETS (typed) =====
    "OutputPresetCreate",
    "OutputPresetUpdate",
    "OutputPresetResponse",
    # ===== RECORDING TEMPLATES (typed) =====
    "RecordingTemplateCreate",
    "RecordingTemplateUpdate",
    "RecordingTemplateResponse",
    "RecordingTemplateListResponse",
    # ===== OPERATIONS =====
    "BulkDeleteResponse",
    "RematchTaskResponse",
    "SyncSourceResponse",
    "SyncTaskResponse",
    # ===== NESTED TYPED MODELS =====
    # Matching Rules
    "MatchingRules",
    # Processing Config
    "TemplateProcessingConfig",
    "TranscriptionProcessingConfig",
    # Metadata Config
    "TemplateMetadataConfig",
    "VKMetadataConfig",
    "YouTubeMetadataConfig",
    # Output Config
    "TemplateOutputConfig",
    # Preset Metadata (typed)
    "YouTubePresetMetadata",
    "VKPresetMetadata",
    # Source Config (typed)
    "SourceConfig",
    "ZoomSourceConfig",
    "GoogleDriveSourceConfig",
    "YandexDiskSourceConfig",
    "LocalFileSourceConfig",
    # ===== ENUMS =====
    "TopicsDisplayFormat",
    "YouTubePrivacy",
    "YouTubeLicense",
    "VKPrivacyLevel",
    # ===== COMPONENTS =====
    "TopicsDisplayConfig",
]
