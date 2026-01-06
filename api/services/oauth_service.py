"""OAuth service for handling authorization and token exchange."""

from typing import Any
from urllib.parse import urlencode

import aiohttp

from api.services.oauth_platforms import OAuthPlatformConfig
from api.services.oauth_state import OAuthStateManager
from logger import get_logger

logger = get_logger()


class OAuthService:
    """Handles OAuth operations for platforms (YouTube, VK)."""

    def __init__(self, config: OAuthPlatformConfig, state_manager: OAuthStateManager):
        self.config = config
        self.state_manager = state_manager

    async def get_authorization_url(
        self,
        user_id: int,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate OAuth authorization URL.

        Args:
            user_id: User ID for multi-tenancy
            ip_address: Optional IP address for security

        Returns:
            Dict with authorization_url, state, and expires_in
        """
        state = await self.state_manager.create_state(user_id, self.config.platform_id, ip_address)

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": self.config.response_type,
            "state": state,
        }

        # Platform-specific parameters
        if self.config.platform_id == "youtube":
            params["scope"] = " ".join(self.config.scopes)
            params["access_type"] = self.config.access_type
            params["prompt"] = "consent"  # Force consent screen for refresh token
        elif self.config.platform_id == "vk_video":
            params["scope"] = ",".join(self.config.scopes)
            params["display"] = "page"
            params["v"] = "5.131"

        authorization_url = f"{self.config.authorization_url}?{urlencode(params)}"

        logger.info(f"OAuth authorization URL generated: user_id={user_id} platform={self.config.platform_id}")

        return {
            "authorization_url": authorization_url,
            "state": state,
            "expires_in": self.state_manager.ttl,
            "platform": self.config.platform_id,
        }

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth callback

        Returns:
            Token data (access_token, refresh_token, expires_in, etc)

        Raises:
            aiohttp.ClientError: If token exchange fails
        """
        data = {
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
        }

        # Platform-specific handling
        if self.config.platform_id == "youtube":
            return await self._exchange_google_token(data)
        elif self.config.platform_id == "vk_video":
            return await self._exchange_vk_token(data)
        else:
            raise ValueError(f"Unsupported platform: {self.config.platform_id}")

    async def _exchange_google_token(self, data: dict) -> dict[str, Any]:
        """Exchange Google/YouTube authorization code for token."""
        async with aiohttp.ClientSession() as session:
            async with session.post(self.config.token_url, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Google token exchange failed: status={response.status} error={error_text}")
                    raise aiohttp.ClientError(f"Token exchange failed: {response.status}")

                token_data = await response.json()
                logger.info(f"Google token obtained: has_refresh={bool(token_data.get('refresh_token'))}")
                return token_data

    async def _exchange_vk_token(self, data: dict) -> dict[str, Any]:
        """Exchange VK authorization code for token."""
        url = "https://oauth.vk.com/access_token"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"VK token exchange failed: status={response.status} error={error_text}")
                    raise aiohttp.ClientError(f"Token exchange failed: {response.status}")

                token_data = await response.json()

                if "error" in token_data:
                    logger.error(f"VK token error: {token_data['error']}")
                    raise aiohttp.ClientError(f"VK error: {token_data['error']}")

                logger.info("VK token obtained successfully")
                return token_data

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh access token using refresh token (YouTube only).

        Args:
            refresh_token: Refresh token

        Returns:
            New token data

        Raises:
            ValueError: If platform doesn't support refresh
            aiohttp.ClientError: If refresh fails
        """
        if self.config.platform_id != "youtube":
            raise ValueError(f"Platform {self.config.platform_id} does not support token refresh")

        data = {
            "refresh_token": refresh_token,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "refresh_token",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.config.token_url, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Token refresh failed: status={response.status} error={error_text}")
                    raise aiohttp.ClientError(f"Token refresh failed: {response.status}")

                token_data = await response.json()
                logger.info("Access token refreshed successfully")
                return token_data

    async def validate_token(self, access_token: str) -> bool:
        """
        Validate token by making test API call.

        Args:
            access_token: Access token to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            if self.config.platform_id == "youtube":
                return await self._validate_youtube_token(access_token)
            elif self.config.platform_id == "vk_video":
                return await self._validate_vk_token(access_token)
            else:
                logger.warning(f"Token validation not implemented for {self.config.platform_id}")
                return True  # Assume valid
        except Exception as e:
            logger.error(f"Token validation error: {e}")
            return False

    async def _validate_youtube_token(self, access_token: str) -> bool:
        """Validate YouTube token via API call."""
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part": "id", "mine": "true"}
        headers = {"Authorization": f"Bearer {access_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    logger.debug("YouTube token validated successfully")
                    return True
                else:
                    logger.warning(f"YouTube token validation failed: status={response.status}")
                    return False

    async def _validate_vk_token(self, access_token: str) -> bool:
        """Validate VK token via API call."""
        url = "https://api.vk.com/method/users.get"
        params = {"access_token": access_token, "v": "5.131"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if "error" not in data:
                        logger.debug("VK token validated successfully")
                        return True

                logger.warning(f"VK token validation failed: status={response.status}")
                return False

