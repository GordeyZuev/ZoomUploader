"""Universal token error handler for YouTube and VK with automatic retry.

Simple decorator that catches auth errors and refreshes tokens automatically.
"""

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request

from logger import get_logger

logger = get_logger()

T = TypeVar("T")


class TokenRefreshError(Exception):
    """Raised when token cannot be refreshed (YouTube or VK)."""

    def __init__(self, platform: str, message: str, original_error: Exception | None = None):
        super().__init__(f"[{platform}] {message}")
        self.platform = platform
        self.original_error = original_error


# Backward compatibility
YouTubeTokenError = TokenRefreshError


def is_youtube_auth_error(error: Exception) -> bool:
    """Check if error is YouTube authentication error (401/403)."""
    try:
        from googleapiclient.errors import HttpError

        if isinstance(error, HttpError) and error.resp:
            return error.resp.status in (401, 403)
    except ImportError:
        pass
    return False


def is_vk_auth_error(response_data: dict) -> bool:
    """Check if VK response contains authentication error (codes 5, 28)."""
    if not isinstance(response_data, dict):
        return False

    error_info = response_data.get("error")
    if error_info and isinstance(error_info, dict):
        error_code = error_info.get("error_code")
        return error_code in (5, 28)  # Invalid token or expired

    return False


def requires_valid_token(max_retries: int = 1):
    """Decorator for YouTube: catches 401/403 errors and refreshes token.

    Requires: self.credentials, self.credential_provider, self.service
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(self, *args: Any, **kwargs: Any) -> T:
            from googleapiclient.errors import HttpError

            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(self, *args, **kwargs)

                except HttpError as e:
                    last_error = e

                    if not is_youtube_auth_error(e):
                        raise

                    if attempt >= max_retries:
                        logger.error(f"YouTube auth failed after {max_retries} retries")
                        raise TokenRefreshError(
                            "youtube",
                            f"Token refresh failed after {max_retries} attempts",
                            original_error=e,
                        ) from e

                    logger.warning(f"YouTube {e.resp.status} error, refreshing token (attempt {attempt + 1})")

                    try:
                        if not hasattr(self, "credentials") or not self.credentials:
                            raise TokenRefreshError("youtube", "No credentials", original_error=e) from e

                        if not self.credentials.refresh_token:
                            raise TokenRefreshError("youtube", "No refresh_token", original_error=e) from e

                        self.credentials.refresh(Request())

                        if hasattr(self, "credential_provider") and self.credential_provider:
                            await self.credential_provider.update_google_credentials(self.credentials)

                        if hasattr(self, "service") and self.service:
                            from googleapiclient.discovery import build
                            self.service = build("youtube", "v3", credentials=self.credentials)

                        logger.info("YouTube token refreshed")
                        continue

                    except RefreshError as refresh_err:
                        raise TokenRefreshError(
                            "youtube", "Refresh failed", original_error=refresh_err
                        ) from refresh_err

            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in decorator")

        return wrapper
    return decorator


def requires_valid_vk_token(max_retries: int = 1):
    """Decorator for VK: catches error_code 5/28 and refreshes token.

    Requires: self.config.access_token, self.credential_provider
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(self, *args: Any, **kwargs: Any) -> T:
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    result = await func(self, *args, **kwargs)

                    # VK может вернуть результат с ошибкой внутри
                    if isinstance(result, dict) and is_vk_auth_error(result):
                        if attempt >= max_retries:
                            error_info = result.get("error", {})
                            error_msg = error_info.get("error_msg", "Unknown")
                            logger.error(f"VK auth failed after {max_retries} retries: {error_msg}")
                            raise TokenRefreshError("vk", f"Token invalid: {error_msg}")

                        logger.warning(f"VK token error, refreshing (attempt {attempt + 1})")

                        if not hasattr(self, "credential_provider") or not self.credential_provider:
                            raise TokenRefreshError("vk", "No credential_provider")

                        if hasattr(self.credential_provider, "refresh_vk_token"):
                            refreshed = await self.credential_provider.refresh_vk_token()
                            if refreshed and "access_token" in refreshed:
                                self.config.access_token = refreshed["access_token"]
                                logger.info("VK token refreshed")
                                continue
                            raise TokenRefreshError("vk", "Failed to refresh VK token")

                        raise TokenRefreshError("vk", "Credential provider doesn't support VK refresh")

                    return result

                except Exception as e:
                    last_error = e
                    if attempt >= max_retries:
                        raise

                    # Для неожиданных ошибок не пытаемся обновить токен
                    raise

            if last_error:
                raise last_error
            raise RuntimeError("Unexpected state in decorator")

        return wrapper
    return decorator
