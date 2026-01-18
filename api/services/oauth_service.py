"""OAuth service for handling authorization and token exchange."""

import json
from typing import Any
from urllib.parse import urlencode

import aiohttp

from api.services.oauth_platforms import OAuthPlatformConfig
from api.services.oauth_state import OAuthStateManager
from api.services.pkce_utils import generate_pkce_pair
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
        # Generate PKCE pair if platform requires it
        code_verifier = None
        if self.config.use_pkce:
            code_verifier, code_challenge = generate_pkce_pair()
            logger.debug(f"PKCE enabled for {self.config.platform_id}: code_challenge generated")

        # Create state (with code_verifier if PKCE is used)
        state = await self.state_manager.create_state(
            user_id,
            self.config.platform_id,
            ip_address,
            code_verifier=code_verifier,
        )

        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": self.config.response_type,
            "state": state,
        }

        # Add PKCE parameters if enabled
        if self.config.use_pkce and code_verifier:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        # Platform-specific parameters
        if self.config.platform_id == "youtube":
            params["scope"] = " ".join(self.config.scopes)
            params["access_type"] = self.config.access_type
            params["prompt"] = "consent"  # Force consent screen for refresh token
        elif self.config.platform_id == "vk_video":
            params["scope"] = " ".join(self.config.scopes)  # VK ID uses space-separated scopes
            params["prompt"] = "consent"  # Request consent for refresh token
        elif self.config.platform_id == "zoom":
            params["scope"] = " ".join(self.config.scopes)  # Zoom uses space-separated scopes

        authorization_url = f"{self.config.authorization_url}?{urlencode(params)}"

        logger.info(
            f"OAuth authorization URL generated: user_id={user_id} platform={self.config.platform_id} pkce={self.config.use_pkce}"
        )

        return {
            "authorization_url": authorization_url,
            "state": state,
            "expires_in": self.state_manager.ttl,
            "platform": self.config.platform_id,
        }

    async def exchange_code_for_token(
        self, code: str, code_verifier: str | None = None, device_id: str | None = None
    ) -> dict[str, Any]:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from OAuth callback
            code_verifier: PKCE code_verifier (required for platforms using PKCE)
            device_id: Device ID from VK (required for VK ID OAuth)

        Returns:
            Token data (access_token, refresh_token, expires_in, etc)

        Raises:
            aiohttp.ClientError: If token exchange fails
            ValueError: If PKCE is required but code_verifier is missing
        """
        # Validate PKCE requirements
        if self.config.use_pkce and not code_verifier:
            raise ValueError(f"Platform {self.config.platform_id} requires PKCE but code_verifier is missing")

        data = {
            "code": code,
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
        }

        # Add client_secret if available (not required for PKCE)
        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret

        # Add code_verifier for PKCE
        if code_verifier:
            data["code_verifier"] = code_verifier

        # Add device_id for VK ID
        if device_id:
            data["device_id"] = device_id

        # Platform-specific handling
        if self.config.platform_id == "youtube":
            return await self._exchange_google_token(data)
        if self.config.platform_id == "vk_video":
            return await self._exchange_vk_token(data)
        if self.config.platform_id == "zoom":
            return await self._exchange_zoom_token(data)
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
        """Exchange VK authorization code for token using VK ID API.

        VK ID uses POST to /oauth2/auth with state and device_id in addition to standard OAuth params.
        Documentation: https://id.vk.ru/about/business/go/docs/ru/vkid/latest/vk-id/connection/api-description
        """
        url = self.config.token_url

        # Log the request for debugging
        logger.debug(f"VK token exchange: url={url} data_keys={list(data.keys())}")

        # VK ID token exchange requires form-encoded data
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as response:
                response_text = await response.text()

                if response.status != 200:
                    logger.error(
                        f"VK token exchange failed: status={response.status} url={url} error={response_text[:500]}"
                    )
                    raise aiohttp.ClientError(f"Token exchange failed: {response.status}")

                try:
                    token_data = json.loads(response_text) if response_text else {}
                except json.JSONDecodeError:
                    logger.error(f"VK token response is not JSON: {response_text[:500]}")
                    raise aiohttp.ClientError("Invalid JSON response from VK")

                if "error" in token_data:
                    logger.error(
                        f"VK token error: {token_data.get('error')} - {token_data.get('error_description', '')}"
                    )
                    raise aiohttp.ClientError(f"VK error: {token_data['error']}")

                logger.info(f"VK ID token obtained: has_refresh={bool(token_data.get('refresh_token'))}")
                return token_data

    async def _exchange_zoom_token(self, data: dict) -> dict[str, Any]:
        """Exchange Zoom authorization code for token.

        Zoom OAuth uses Basic Authentication with client_id:client_secret encoded in Base64.
        Documentation: https://developers.zoom.us/docs/integrations/oauth/
        """
        import base64

        # Zoom requires Basic Auth (client_id:client_secret in base64)
        auth_string = f"{self.config.client_id}:{self.config.client_secret}"
        auth_bytes = auth_string.encode("ascii")
        auth_b64 = base64.b64encode(auth_bytes).decode("ascii")

        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Remove client_secret from data (it's in Authorization header)
        token_data = {k: v for k, v in data.items() if k != "client_secret"}

        logger.debug(f"Zoom token exchange: url={self.config.token_url} data_keys={list(token_data.keys())}")

        async with aiohttp.ClientSession() as session:
            async with session.post(self.config.token_url, data=token_data, headers=headers) as response:
                response_text = await response.text()

                if response.status != 200:
                    logger.error(f"Zoom token exchange failed: status={response.status} error={response_text[:500]}")
                    raise aiohttp.ClientError(f"Token exchange failed: {response.status}")

                try:
                    token_response = json.loads(response_text) if response_text else {}
                except json.JSONDecodeError:
                    logger.error(f"Zoom token response is not JSON: {response_text[:500]}")
                    raise aiohttp.ClientError("Invalid JSON response from Zoom")

                if "error" in token_response:
                    logger.error(
                        f"Zoom token error: {token_response.get('error')} - {token_response.get('error_description', '')}"
                    )
                    raise aiohttp.ClientError(f"Zoom error: {token_response['error']}")

                logger.info(f"Zoom token obtained: has_refresh={bool(token_response.get('refresh_token'))}")
                return token_response

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh access token using refresh token (YouTube and VK ID).

        Args:
            refresh_token: Refresh token

        Returns:
            New token data

        Raises:
            ValueError: If platform doesn't support refresh or token_url is not set
            aiohttp.ClientError: If refresh fails
        """
        if not self.config.token_url:
            raise ValueError(f"Platform {self.config.platform_id} does not have token_url configured")

        if self.config.platform_id == "youtube":
            return await self._refresh_google_token(refresh_token)
        if self.config.platform_id == "vk_video":
            return await self._refresh_vk_token(refresh_token)
        if self.config.platform_id == "zoom":
            return await self._refresh_zoom_token(refresh_token)
        raise ValueError(f"Token refresh not supported for {self.config.platform_id}")

    async def _refresh_google_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh Google/YouTube token."""
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
                    logger.error(f"Google token refresh failed: status={response.status} error={error_text}")
                    raise aiohttp.ClientError(f"Token refresh failed: {response.status}")

                token_data = await response.json()
                logger.info("Google access token refreshed successfully")
                return token_data

    async def _refresh_vk_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh VK token using VK ID API."""
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
                    logger.error(f"VK token refresh failed: status={response.status} error={error_text}")
                    raise aiohttp.ClientError(f"Token refresh failed: {response.status}")

                token_data = await response.json()

                if "error" in token_data:
                    logger.error(f"VK token refresh error: {token_data['error']}")
                    raise aiohttp.ClientError(f"VK error: {token_data['error']}")

                logger.info("VK access token refreshed successfully")
                return token_data

    async def _refresh_zoom_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh Zoom token using refresh_token."""
        import base64

        # Zoom requires Basic Auth for token refresh
        auth_string = f"{self.config.client_id}:{self.config.client_secret}"
        auth_bytes = auth_string.encode("ascii")
        auth_b64 = base64.b64encode(auth_bytes).decode("ascii")

        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.config.token_url, data=data, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Zoom token refresh failed: status={response.status} error={error_text}")
                    raise aiohttp.ClientError(f"Token refresh failed: {response.status}")

                token_data = await response.json()

                if "error" in token_data:
                    logger.error(f"Zoom token refresh error: {token_data['error']}")
                    raise aiohttp.ClientError(f"Zoom error: {token_data['error']}")

                logger.info("Zoom access token refreshed successfully")
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
            if self.config.platform_id == "vk_video":
                return await self._validate_vk_token(access_token)
            if self.config.platform_id == "zoom":
                return await self._validate_zoom_token(access_token)
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
                logger.warning(f"YouTube token validation failed: status={response.status}")
                return False

    async def _validate_vk_token(self, access_token: str) -> bool:
        """Validate VK token via API call."""
        url = "https://api.vk.com/method/users.get"
        params = {"access_token": access_token, "v": "5.131"}

        async with aiohttp.ClientSession() as session, session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if "error" not in data:
                    logger.debug("VK token validated successfully")
                    return True

            logger.warning(f"VK token validation failed: status={response.status}")
            return False

    async def _validate_zoom_token(self, access_token: str) -> bool:
        """Validate Zoom token via API call."""
        url = "https://api.zoom.us/v2/users/me"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with aiohttp.ClientSession() as session, session.get(url, headers=headers) as response:
            if response.status == 200:
                logger.debug("Zoom token validated successfully")
                return True
            logger.warning(f"Zoom token validation failed: status={response.status}")
            return False
