"""Service for resolving recording configuration hierarchy.

Config priority (lowest to highest):
1. User config (defaults)
2. Template config (if recording.template_id is set)
3. recording.processing_preferences (manual override - highest priority)
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.config_repos import UserConfigRepository
from api.repositories.template_repos import RecordingTemplateRepository
from database.models import RecordingModel
from logger import get_logger

logger = get_logger()


class ConfigResolver:
    """Service for resolving recording configuration from multiple sources."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_config_repo = UserConfigRepository(session)
        self.template_repo = RecordingTemplateRepository(session)

    async def resolve_processing_config(
        self,
        recording: RecordingModel,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Resolve processing configuration with hierarchy.

        Logic:
        1. If recording.processing_preferences exists → return it (manual config wins)
        2. Else if recording.template_id exists → merge user_config + template.processing_config
        3. Else → return user_config only

        Args:
            recording: Recording model instance
            user_id: User ID for config resolution

        Returns:
            Resolved processing configuration dict
        """
        # 1. Check for manual override (highest priority)
        if recording.processing_preferences:
            logger.debug(
                f"Using manual processing_preferences for recording {recording.id}"
            )
            return recording.processing_preferences

        # 2. Get user config as base
        user_config = await self._get_user_config(user_id)
        processing_config = user_config.get("processing", {})

        # 3. Merge with template config if exists
        if recording.template_id:
            template = await self.template_repo.find_by_id(recording.template_id, user_id)
            if template and template.processing_config:
                logger.debug(
                    f"Merging template '{template.name}' config for recording {recording.id}"
                )
                processing_config = self._merge_configs(
                    processing_config, template.processing_config
                )
            else:
                logger.warning(
                    f"Recording {recording.id} has template_id={recording.template_id} "
                    f"but template not found or has no config"
                )

        return processing_config

    async def get_base_config_for_edit(
        self,
        recording: RecordingModel,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Get current resolved configuration for editing.

        Used in GET /recordings/{id}/config to show user what they're editing.
        Returns the current effective config (resolved from user + template).

        Args:
            recording: Recording model instance
            user_id: User ID

        Returns:
            Dict with:
            - processing_config: Current resolved config
            - output_config: Output presets configuration
            - metadata_config: Metadata templates
            - has_manual_override: bool
            - template_name: str | None
        """
        # Get processing config
        if recording.processing_preferences:
            processing_config = recording.processing_preferences
            has_manual_override = True
        else:
            processing_config = await self.resolve_processing_config(recording, user_id)
            has_manual_override = False

        # Get output config
        output_config = await self.resolve_output_config(recording, user_id)

        # Get metadata config
        metadata_config = await self.resolve_metadata_config(recording, user_id)

        # Get template name if exists
        template_name = None
        if recording.template_id:
            template = await self.template_repo.find_by_id(recording.template_id, user_id)
            if template:
                template_name = template.name

        return {
            "processing_config": processing_config,
            "output_config": output_config,
            "metadata_config": metadata_config,
            "has_manual_override": has_manual_override,
            "template_name": template_name,
            "template_id": recording.template_id,
        }

    async def resolve_output_config(
        self,
        recording: RecordingModel,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Resolve output configuration (preset_ids for platforms).

        Priority same as processing_config:
        1. recording.processing_preferences.output_config
        2. template.output_config
        3. user_config.output (if exists)

        Args:
            recording: Recording model instance
            user_id: User ID

        Returns:
            Dict with output configuration
        """
        # Check manual override first
        if recording.processing_preferences and "output_config" in recording.processing_preferences:
            return recording.processing_preferences["output_config"]

        # Get user config base
        user_config = await self._get_user_config(user_id)
        output_config = user_config.get("output", {})

        # Merge with template if exists
        if recording.template_id:
            template = await self.template_repo.find_by_id(recording.template_id, user_id)
            if template and template.output_config:
                output_config = self._merge_configs(output_config, template.output_config)

        return output_config

    async def resolve_metadata_config(
        self,
        recording: RecordingModel,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Resolve metadata configuration (title, description, tags templates).

        NOTE: Metadata (title_template, description_template, tags) is primarily
        configured in output_preset.preset_metadata, not in template.
        This method is kept for backward compatibility with manual overrides.

        Priority:
        1. recording.processing_preferences.metadata_config (manual override)
        2. user_config.metadata (if exists)

        Args:
            recording: Recording model instance
            user_id: User ID

        Returns:
            Dict with metadata configuration
        """
        # Check manual override
        if recording.processing_preferences and "metadata_config" in recording.processing_preferences:
            return recording.processing_preferences["metadata_config"]

        # Get user config base
        user_config = await self._get_user_config(user_id)
        metadata_config = user_config.get("metadata", {})

        return metadata_config

    async def _get_user_config(self, user_id: int) -> dict[str, Any]:
        """Get user configuration or return empty dict."""
        try:
            user_config_model = await self.user_config_repo.get_by_user_id(user_id)
            return user_config_model.config_data if user_config_model else {}
        except Exception as e:
            logger.warning(f"Failed to get user config for user {user_id}: {e}")
            return {}

    def _merge_configs(
        self,
        base: dict[str, Any],
        override: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Deep merge two configuration dicts.

        Override values take precedence over base values.
        Nested dicts are merged recursively.

        Args:
            base: Base configuration dict
            override: Override configuration dict

        Returns:
            Merged configuration dict
        """
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursive merge for nested dicts
                result[key] = self._merge_configs(result[key], value)
            else:
                # Override value
                result[key] = value

        return result

