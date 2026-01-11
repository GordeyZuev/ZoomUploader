"""Credentials validation helper."""

from typing import Any

from api.schemas.credentials.platform_credentials import (
    VKCredentialsManual,
    YouTubeCredentialsManual,
    ZoomCredentialsManual,
)
from logger import get_logger

logger = get_logger()


class CredentialsValidator:
    """Validates platform credentials using Pydantic schemas."""

    @staticmethod
    def validate_youtube(credentials: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate YouTube credentials.

        Args:
            credentials: Credentials dict

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            YouTubeCredentialsManual(**credentials)
            return True, None
        except Exception as e:
            error = f"YouTube credentials validation failed: {str(e)}"
            logger.error(error)
            return False, error

    @staticmethod
    def validate_vk(credentials: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate VK credentials.

        Args:
            credentials: Credentials dict

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            VKCredentialsManual(**credentials)

            # Additional validation
            if "access_token" in credentials:
                token = credentials["access_token"]
                if len(token) < 10:
                    return False, "VK access_token too short (min 10 characters)"

            # Warn if user_id is missing
            if "user_id" not in credentials or credentials["user_id"] is None:
                logger.warning("VK credentials missing user_id - functionality may be limited")

            return True, None
        except Exception as e:
            error = f"VK credentials validation failed: {str(e)}"
            logger.error(error)
            return False, error

    @staticmethod
    def validate_zoom(credentials: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate Zoom credentials.

        Args:
            credentials: Credentials dict

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            ZoomCredentialsManual(**credentials)
            return True, None
        except Exception as e:
            error = f"Zoom credentials validation failed: {str(e)}"
            logger.error(error)
            return False, error

    @staticmethod
    def validate(platform: str, credentials: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Validate credentials for any platform.

        Args:
            platform: Platform name (youtube, vk_video, zoom)
            credentials: Credentials dict

        Returns:
            Tuple of (is_valid, error_message)
        """
        platform_lower = platform.lower()

        if platform_lower == "youtube":
            return CredentialsValidator.validate_youtube(credentials)
        elif platform_lower in ["vk", "vk_video"]:
            return CredentialsValidator.validate_vk(credentials)
        elif platform_lower == "zoom":
            return CredentialsValidator.validate_zoom(credentials)
        else:
            return False, f"Unknown platform: {platform}"

    @staticmethod
    def get_required_fields(platform: str) -> list[str]:
        """
        Get list of required fields for a platform.

        Args:
            platform: Platform name

        Returns:
            List of required field names
        """
        platform_lower = platform.lower()

        if platform_lower == "youtube":
            return ["token", "client_id", "client_secret", "scopes"]
        elif platform_lower in ["vk", "vk_video"]:
            return ["access_token"]
        elif platform_lower == "zoom":
            return ["account_id", "client_id", "client_secret"]
        else:
            return []

    @staticmethod
    def get_optional_fields(platform: str) -> list[str]:
        """
        Get list of optional fields for a platform.

        Args:
            platform: Platform name

        Returns:
            List of optional field names
        """
        platform_lower = platform.lower()

        if platform_lower == "youtube":
            return ["refresh_token", "expiry", "token_uri"]
        elif platform_lower in ["vk", "vk_video"]:
            return [
                "refresh_token",
                "user_id",
                "expires_in",
                "expiry",
                "client_id",
                "client_secret",
                "group_id",
                "album_id",
                "app_id",
                "scope",
            ]
        elif platform_lower == "zoom":
            return ["account"]
        else:
            return []

