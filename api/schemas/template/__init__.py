"""Схемы для шаблонов, конфигураций, источников и пресетов."""

from .config import BaseConfigCreate, BaseConfigResponse, BaseConfigUpdate
from .input_source import InputSourceCreate, InputSourceResponse, InputSourceUpdate
from .output_preset import OutputPresetCreate, OutputPresetResponse, OutputPresetUpdate
from .template import RecordingTemplateCreate, RecordingTemplateResponse, RecordingTemplateUpdate

__all__ = [
    # Base configs
    "BaseConfigCreate",
    "BaseConfigUpdate",
    "BaseConfigResponse",
    # Input sources
    "InputSourceCreate",
    "InputSourceUpdate",
    "InputSourceResponse",
    # Output presets
    "OutputPresetCreate",
    "OutputPresetUpdate",
    "OutputPresetResponse",
    # Recording templates
    "RecordingTemplateCreate",
    "RecordingTemplateUpdate",
    "RecordingTemplateResponse",
]

