"""VK Token validation and management service."""

from datetime import datetime, timedelta

import aiohttp

from logger import get_logger

logger = get_logger()


class VKTokenService:
    """Service for VK Implicit Flow token validation and management."""

    VK_API_VERSION = "5.131"
    VK_API_BASE = "https://api.vk.com/method"

    async def validate_token(self, token: str) -> tuple[bool, str, dict | None]:
        """
        Validate VK access token.

        Args:
            token: VK access token to validate

        Returns:
            Tuple of (is_valid, error_type, user_data)
            - is_valid: True if token is valid
            - error_type: "success" | "ip_mismatch" | "api_error" | "http_error" | "network_error"
            - user_data: User data from VK API if valid (first_name, last_name, id)
        """
        try:
            async with aiohttp.ClientSession() as session:
                params = {"access_token": token, "v": self.VK_API_VERSION}
                async with session.get(f"{self.VK_API_BASE}/users.get", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            error = data["error"]
                            error_code = error.get("error_code")
                            error_subcode = error.get("error_subcode")

                            # Check for IP mismatch error
                            if error_code == 5 and error_subcode == 1130:
                                logger.warning(
                                    f"VK token validation failed: IP mismatch (code={error_code}, subcode={error_subcode})"
                                )
                                return False, "ip_mismatch", None

                            logger.error(f"VK API error: {error.get('error_msg', 'Unknown error')}")
                            return False, "api_error", None

                        # Token is valid
                        user = data["response"][0]
                        logger.info(
                            f"VK token validated successfully: user_id={user['id']} "
                            f"name={user['first_name']} {user['last_name']}"
                        )
                        return True, "success", user

                    logger.error(f"VK API HTTP error: status={response.status}")
                    return False, "http_error", None

        except aiohttp.ClientError as e:
            logger.error(f"VK token validation network error: {e}")
            return False, "network_error", None
        except Exception as e:
            logger.error(f"VK token validation unexpected error: {e}")
            return False, "network_error", None

    async def get_user_id(self, token: str) -> int | None:
        """
        Get VK user_id from token.

        Args:
            token: VK access token

        Returns:
            VK user_id or None if failed
        """
        is_valid, error_type, user_data = await self.validate_token(token)
        if is_valid and user_data:
            return user_data.get("id")
        return None

    def calculate_expiry(self, expires_in: int = 86400) -> datetime:
        """
        Calculate token expiry datetime.

        Args:
            expires_in: Token lifetime in seconds (default 24 hours)

        Returns:
            Expiry datetime (UTC)
        """
        return datetime.utcnow() + timedelta(seconds=expires_in)

    def format_expiry_iso(self, expiry: datetime) -> str:
        """
        Format expiry datetime to ISO format with timezone.

        Args:
            expiry: Expiry datetime

        Returns:
            ISO formatted string with 'Z' suffix
        """
        return expiry.isoformat() + "Z"

    def get_error_message(self, error_type: str) -> dict[str, str]:
        """
        Get user-friendly error message for error type.

        Args:
            error_type: Error type from validate_token

        Returns:
            Dict with error details and recommendations
        """
        error_messages = {
            "ip_mismatch": {
                "error": "IP address mismatch",
                "message": "Token is bound to a different IP address",
                "solution": "Please obtain a new token from your current IP address",
            },
            "api_error": {
                "error": "VK API error",
                "message": "Token validation failed due to VK API error",
                "solution": "Check token permissions and try again",
            },
            "http_error": {
                "error": "HTTP error",
                "message": "Failed to communicate with VK API",
                "solution": "Please try again later",
            },
            "network_error": {
                "error": "Network error",
                "message": "Network connection to VK API failed",
                "solution": "Check your internet connection and try again",
            },
        }
        return error_messages.get(error_type, {"error": "Unknown error", "message": "Token validation failed"})

