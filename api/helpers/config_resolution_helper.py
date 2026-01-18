"""Helper for resolving configuration in Celery tasks.

Provides reusable config resolution logic for template-driven pipeline.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.config_repos import UserConfigRepository
from api.repositories.recording_repos import RecordingAsyncRepository
from api.repositories.template_repos import RecordingTemplateRepository
from api.services.config_resolver import ConfigResolver
from database.models import RecordingModel
from logger import get_logger

logger = get_logger()


async def resolve_full_config(
    session: AsyncSession,
    recording_id: int,
    user_id: int,
    manual_override: dict[str, Any] | None = None,
    include_output_config: bool = False,
) -> tuple[dict[str, Any], RecordingModel] | tuple[dict[str, Any], dict[str, Any], RecordingModel]:
    """
    Resolve full configuration for recording with hierarchy.

    Config hierarchy (lowest to highest priority):
    1. user_config (base defaults)
    2. template.processing_config (if recording.template_id set)
    3. recording.processing_preferences (if exists)
    4. manual_override (highest priority)

    Args:
        session: AsyncSession
        recording_id: Recording ID
        user_id: User ID
        manual_override: Optional manual config override
        include_output_config: If True, also resolve and return output_config

    Returns:
        If include_output_config=False: Tuple of (resolved_config, recording)
        If include_output_config=True: Tuple of (resolved_config, output_config, recording)

    Raises:
        ValueError: If recording not found
    """
    # Get recording
    recording_repo = RecordingAsyncRepository(session)
    recording = await recording_repo.get_by_id(recording_id, user_id)

    if not recording:
        raise ValueError(f"Recording {recording_id} not found")

    # Get full user config as base
    user_config_repo = UserConfigRepository(session)
    user_config_model = await user_config_repo.get_by_user_id(user_id)
    full_config = user_config_model.config_data if user_config_model else {}

    # Initialize config resolver for merging
    config_resolver = ConfigResolver(session)

    # Merge with template if exists
    if recording.template_id:
        template_repo = RecordingTemplateRepository(session)
        template = await template_repo.find_by_id(recording.template_id, user_id)
        if template and template.processing_config:
            logger.debug(f"Merging template '{template.name}' config for recording {recording_id}")
            full_config = config_resolver._merge_configs(full_config, template.processing_config)

    # Merge with recording.processing_preferences if exists (higher priority)
    if recording.processing_preferences:
        logger.debug(f"Merging recording.processing_preferences for recording {recording_id}")
        full_config = config_resolver._merge_configs(full_config, recording.processing_preferences)

    # Merge with manual_override (absolute highest priority)
    if manual_override:
        logger.debug(f"Applying manual_override for recording {recording_id}")
        full_config = config_resolver._merge_configs(full_config, manual_override)

    # Flatten nested processing_config structure if exists
    # Templates store: {"processing_config": {"transcription": {...}}}
    # Tasks expect flat: {"transcription": {...}}
    # NOTE: metadata_config and output_config should NOT be flattened!
    if "processing_config" in full_config:
        nested_config = full_config.pop("processing_config")
        full_config = config_resolver._merge_configs(full_config, nested_config)
        logger.debug(f"Flattened nested processing_config for recording {recording_id}")

    logger.info(
        f"Resolved config for recording {recording_id}: "
        f"template_id={recording.template_id}, "
        f"has_preferences={bool(recording.processing_preferences)}, "
        f"has_override={bool(manual_override)}"
    )

    # Optionally include output_config
    if include_output_config:
        output_config = await config_resolver.resolve_output_config(recording, user_id)
        return full_config, output_config, recording

    return full_config, recording
