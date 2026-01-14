"""Service for resolving recording configuration hierarchy.

Config priority (lowest to highest):
1. User config (defaults)
2. Template config (if recording.template_id is set) - always uses current template
3. recording.processing_preferences (user overrides - highest priority)

Note: Template config is always read from the current template state,
so template updates automatically apply to all recordings using that template
(unless they have explicit overrides in processing_preferences).
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.config_repos import UserConfigRepository
from api.repositories.template_repos import OutputPresetRepository, RecordingTemplateRepository
from database.models import RecordingModel
from logger import get_logger

logger = get_logger()


class ConfigResolver:
    """Service for resolving recording configuration from multiple sources."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_config_repo = UserConfigRepository(session)
        self.template_repo = RecordingTemplateRepository(session)
        self.preset_repo = OutputPresetRepository(session)

    async def resolve_processing_config(
        self,
        recording: RecordingModel,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Resolve processing configuration with hierarchy.

        Logic:
        1. Start with user_config as base
        2. If recording.template_id exists → merge template.processing_config (overrides user config)
        3. If recording.processing_preferences exists → merge as overrides (highest priority)

        Args:
            recording: Recording model instance
            user_id: User ID for config resolution

        Returns:
            Resolved processing configuration dict
        """
        # 1. Get user config as base
        user_config = await self._get_user_config(user_id)
        processing_config = user_config.get("processing", {})

        # 2. Merge with template config if exists (overrides user config)
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

        # 3. Apply user overrides if they exist (highest priority)
        if recording.processing_preferences:
            logger.debug(
                f"Applying processing_preferences overrides for recording {recording.id}"
            )
            processing_config = self._merge_configs(
                processing_config, recording.processing_preferences
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
        # Get processing config (always resolved, preferences are merged in resolve_processing_config)
        processing_config = await self.resolve_processing_config(recording, user_id)
        has_manual_override = bool(recording.processing_preferences)

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

        Priority (lowest to highest):
        1. user_config.metadata (base defaults)
        2. template.metadata_config (if recording has template)
        3. recording.processing_preferences.metadata_config (manual override)

        Args:
            recording: Recording model instance
            user_id: User ID

        Returns:
            Dict with metadata configuration
        """
        # Start with user config base
        user_config = await self._get_user_config(user_id)
        metadata_config = user_config.get("metadata", {})

        # Merge with template.metadata_config if exists
        if recording.template_id:
            template = await self.template_repo.find_by_id(recording.template_id, user_id)
            if template and template.metadata_config:
                metadata_config = self._merge_configs(metadata_config, template.metadata_config)

        # Apply manual override (highest priority)
        if recording.processing_preferences and "metadata_config" in recording.processing_preferences:
            metadata_config = self._merge_configs(
                metadata_config,
                recording.processing_preferences["metadata_config"]
            )

        return metadata_config

    async def resolve_upload_metadata(
        self,
        recording: RecordingModel,
        user_id: int,
        preset_id: int,
    ) -> dict[str, Any]:
        """
        Resolve final upload metadata with hierarchy.

        This is the NEW method for preset/template metadata separation.

        Logic (deep merge):
        1. preset.preset_metadata (platform defaults: privacy, embeddable, topics_display)
        2. template.metadata_config (content-specific: title_template, playlist_id, thumbnail_path + overrides)
        3. recording.processing_preferences.metadata_config (manual override - highest priority)

        Args:
            recording: Recording model instance
            user_id: User ID for config resolution
            preset_id: Output preset ID to resolve metadata from

        Returns:
            Final merged metadata dict for upload

        Raises:
            ValueError: If preset not found
        """
        # 1. Get preset metadata (platform defaults)
        preset = await self.preset_repo.find_by_id(preset_id, user_id)
        if not preset:
            raise ValueError(f"Preset {preset_id} not found for user {user_id}")

        final_metadata = preset.preset_metadata or {}
        logger.info(
            f"[Metadata Resolution] Base preset '{preset.name}' (platform={preset.platform}) metadata keys: {list(final_metadata.keys())}"
        )
        if "description_template" in final_metadata:
            logger.info(f"[Metadata Resolution] Preset has description_template: {final_metadata['description_template'][:100]}")
        else:
            logger.info("[Metadata Resolution] Preset does NOT have description_template")

        # 2. Merge with template metadata if exists (with platform-specific support)
        if recording.template_id:
            template = await self.template_repo.find_by_id(recording.template_id, user_id)
            if template and template.metadata_config:
                logger.info(
                    f"[Metadata Resolution] Merging template '{template.name}' metadata_config keys: {list(template.metadata_config.keys())}"
                )

                # NEW: Support platform-specific metadata in template
                # Template can have structure:
                # {
                #   "youtube": {...},  # Platform-specific overrides
                #   "vk": {...},       # Platform-specific overrides
                #   "common": {...},   # Common fields for all platforms
                #   ...                # Top-level fields (backward compatibility)
                # }

                template_meta = template.metadata_config
                platform_key = preset.platform.lower()  # "youtube" or "vk"

                # Step 1: Merge common fields (if exists)
                if "common" in template_meta:
                    logger.info("[Metadata Resolution] Merging template 'common' metadata")
                    final_metadata = self._merge_configs(final_metadata, template_meta["common"])

                # Step 2: Merge platform-specific fields (if exists)
                if platform_key in template_meta:
                    logger.info(f"[Metadata Resolution] Merging template '{platform_key}' specific metadata")
                    final_metadata = self._merge_configs(final_metadata, template_meta[platform_key])

            elif template:
                logger.info(
                    f"[Metadata Resolution] Template '{template.name}' has no metadata_config, using preset only"
                )
            else:
                logger.warning(
                    f"[Metadata Resolution] Recording {recording.id} has template_id={recording.template_id} "
                    f"but template not found"
                )

        # 3. Merge with manual override if exists
        if recording.processing_preferences and "metadata_config" in recording.processing_preferences:
            manual_meta = recording.processing_preferences["metadata_config"]
            logger.debug(
                "[Metadata Resolution] Applying manual override metadata_config"
            )
            final_metadata = self._merge_configs(final_metadata, manual_meta)

        logger.info(
            f"[Metadata Resolution] Final metadata keys for recording {recording.id}: {list(final_metadata.keys())}"
        )
        if "description_template" in final_metadata:
            logger.info(f"[Metadata Resolution] Final description_template: {final_metadata['description_template'][:100]}")
        else:
            logger.info("[Metadata Resolution] Final metadata does NOT have description_template")
        return final_metadata

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
        import copy

        # Deep copy to avoid mutating the original base dict
        result = copy.deepcopy(base)

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursive merge for nested dicts
                result[key] = self._merge_configs(result[key], value)
            else:
                # Override value (deep copy to avoid shared references)
                result[key] = copy.deepcopy(value)

        return result

