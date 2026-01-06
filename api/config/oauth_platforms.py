"""OAuth platform configurations for YouTube and VK."""

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


def load_oauth_config(config_path: str) -> dict:
    """Load OAuth configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"OAuth config file not found: {config_path}")

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def create_youtube_config() -> OAuthPlatformConfig:
    """Create YouTube OAuth configuration."""
    config_path = os.getenv("YOUTUBE_OAUTH_CONFIG", "config/oauth_google.json")

    try:
        config = load_oauth_config(config_path)
    except FileNotFoundError:
        logger.warning(f"YouTube OAuth config not found at {config_path}, using defaults")
        config = {}

    base_url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8080")
    redirect_uri = f"{base_url}/api/v1/oauth/youtube/callback"

    return OAuthPlatformConfig(
        name="YouTube",
        platform_id="youtube",
        authorization_url="https://accounts.google.com/o/oauth2/auth",
        token_url="https://oauth2.googleapis.com/token",
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
    """Create VK OAuth configuration."""
    config_path = os.getenv("VK_OAUTH_CONFIG", "config/oauth_vk.json")

    try:
        config = load_oauth_config(config_path)
    except FileNotFoundError:
        logger.warning(f"VK OAuth config not found at {config_path}, using defaults")
        config = {}

    base_url = os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8080")
    redirect_uri = config.get("redirect_uri", f"{base_url}/api/v1/oauth/vk/callback")

    return OAuthPlatformConfig(
        name="VK",
        platform_id="vk_video",
        authorization_url="https://oauth.vk.com/authorize",
        token_url=None,  # VK uses implicit flow or code in URL
        client_id=config.get("app_id", ""),
        client_secret=config.get("client_secret"),
        scopes=["video", "groups", "wall"],
        redirect_uri=redirect_uri,
        response_type="code",
    )


def get_platform_config(platform: str) -> OAuthPlatformConfig:
    """Get OAuth configuration for a platform."""
    if platform == "youtube":
        return create_youtube_config()
    elif platform in ("vk", "vk_video"):
        return create_vk_config()
    else:
        raise ValueError(f"Unsupported OAuth platform: {platform}")


# Pre-load configs for quick access
try:
    YOUTUBE_CONFIG = create_youtube_config()
    VK_CONFIG = create_vk_config()
    logger.info("OAuth platform configurations loaded successfully")
except Exception as e:
    logger.warning(f"Failed to load OAuth configurations: {e}")
    YOUTUBE_CONFIG = None
    VK_CONFIG = None

