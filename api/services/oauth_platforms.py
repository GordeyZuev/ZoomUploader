"""OAuth platform configurations"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from logger import get_logger

logger = get_logger()


@dataclass
class OAuthPlatformConfig:
    """OAuth configuration for a platform."""

    name: str
    platform_id: str
    authorization_url: str
    token_url: str | None
    client_id: str
    client_secret: str | None
    scopes: list[str]
    redirect_uri: str
    response_type: str = "code"
    access_type: str | None = None
    use_pkce: bool = False  # Whether this platform requires PKCE


def load_oauth_config(config_path: str) -> dict:
    """Load OAuth configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"OAuth config file not found: {config_path}")

    with path.open(encoding="utf-8") as f:
        return json.load(f)


def create_youtube_config() -> OAuthPlatformConfig:
    """Create YouTube OAuth configuration."""
    config_path = os.getenv("YOUTUBE_OAUTH_CONFIG", "config/oauth_google.json")

    try:
        config = load_oauth_config(config_path)
        # Handle both "web" and flat structures
        if "web" in config:
            config = config["web"]
    except FileNotFoundError:
        logger.warning(f"YouTube OAuth config not found at {config_path}, using defaults")
        config = {}

    base_url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    # Use redirect_uris from config if available, otherwise construct from base_url
    redirect_uris = config.get("redirect_uris", [])
    if redirect_uris:
        # Use first redirect_uri that matches our base_url, or just the first one
        redirect_uri = next((uri for uri in redirect_uris if base_url in uri), redirect_uris[0])
    else:
        redirect_uri = f"{base_url}/api/v1/oauth/youtube/callback"

    return OAuthPlatformConfig(
        name="YouTube",
        platform_id="youtube",
        authorization_url=config.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
        token_url=config.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=config.get("client_id", ""),
        client_secret=config.get("client_secret", ""),
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
        redirect_uri=redirect_uri,
        response_type="code",
        access_type="offline",  # Required for refresh token
    )


def create_vk_config() -> OAuthPlatformConfig:
    """Create VK OAuth configuration with support for both old OAuth and new VK ID API."""
    config_path = os.getenv("VK_OAUTH_CONFIG", "config/oauth_vk.json")

    try:
        config = load_oauth_config(config_path)
    except FileNotFoundError:
        logger.warning(f"VK OAuth config not found at {config_path}, using defaults")
        config = {}

    base_url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    redirect_uri = config.get("redirect_uri", f"{base_url}/api/v1/oauth/vk/callback")

    # Check if we should use new VK ID or old VK OAuth
    use_vk_id = config.get("use_vk_id", False)

    if use_vk_id:
        # New VK ID OAuth 2.1 with PKCE and refresh tokens
        # Documentation: https://id.vk.com/about/business/go/docs/ru/vkid/latest/vk-id/connection/start-integration/how-auth-works/auth-flow-web
        logger.info("Using VK ID OAuth 2.1 (with PKCE)")
        return OAuthPlatformConfig(
            name="VK",
            platform_id="vk_video",
            authorization_url="https://id.vk.ru/authorize",
            token_url="https://id.vk.ru/oauth2/auth",  # Correct VK ID token endpoint
            client_id=config.get("app_id", ""),
            client_secret=config.get("client_secret"),
            scopes=["vkid.personal_info", "video", "groups", "wall"],
            redirect_uri=redirect_uri,
            response_type="code",
            access_type=None,
            use_pkce=True,
        )
    # Old VK OAuth (stable, but no refresh tokens)
    logger.info("Using legacy VK OAuth (without PKCE)")
    return OAuthPlatformConfig(
        name="VK",
        platform_id="vk_video",
        authorization_url="https://oauth.vk.com/authorize",
        token_url="https://oauth.vk.com/access_token",
        client_id=config.get("app_id", ""),
        client_secret=config.get("client_secret"),
        scopes=["video", "groups", "wall"],
        redirect_uri=redirect_uri,
        response_type="code",
        access_type=None,
        use_pkce=False,
    )


def create_zoom_config() -> OAuthPlatformConfig:
    """Create Zoom OAuth configuration."""
    config_path = os.getenv("ZOOM_OAUTH_CONFIG", "config/oauth_zoom.json")

    try:
        config = load_oauth_config(config_path)
    except FileNotFoundError:
        logger.warning(f"Zoom OAuth config not found at {config_path}, using defaults")
        config = {}

    base_url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000")
    redirect_uri = config.get("redirect_uri", f"{base_url}/api/v1/oauth/zoom/callback")

    return OAuthPlatformConfig(
        name="Zoom",
        platform_id="zoom",
        authorization_url="https://zoom.us/oauth/authorize",
        token_url="https://zoom.us/oauth/token",
        client_id=config.get("client_id", ""),
        client_secret=config.get("client_secret", ""),
        scopes=[
            # User-level scopes (not admin) for user-managed app
            "cloud_recording:read:list_user_recordings",  # List user's recordings
            "cloud_recording:read:recording",  # Read recording details
            "recording:write:recording",  # Delete recordings
            "user:read:user",  # User info
        ],
        redirect_uri=redirect_uri,
        response_type="code",
        access_type=None,
        use_pkce=False,  # Zoom supports standard OAuth 2.0
    )


def get_platform_config(platform: str) -> OAuthPlatformConfig:
    """Get OAuth configuration for a platform."""
    if platform == "youtube":
        return create_youtube_config()
    if platform in ("vk", "vk_video"):
        return create_vk_config()
    if platform == "zoom":
        return create_zoom_config()
    raise ValueError(f"Unsupported OAuth platform: {platform}")


# Pre-load configs for quick access
try:
    YOUTUBE_CONFIG = create_youtube_config()
    VK_CONFIG = create_vk_config()
    ZOOM_CONFIG = create_zoom_config()
    logger.info("OAuth platform configurations loaded successfully")
except Exception as e:
    logger.warning(f"Failed to load OAuth configurations: {e}")
    YOUTUBE_CONFIG = None
    VK_CONFIG = None
    ZOOM_CONFIG = None
