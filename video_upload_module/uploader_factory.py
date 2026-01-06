"""Factory for creating platform uploaders with database credentials."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.encryption import get_encryption
from api.repositories.auth_repos import UserCredentialRepository
from logger import get_logger

from .config_factory import VKUploadConfig, YouTubeUploadConfig
from .credentials_provider import DatabaseCredentialProvider
from .platforms.vk.uploader import VKUploader
from .platforms.youtube.uploader import YouTubeUploader

logger = get_logger()


async def create_youtube_uploader_from_db(
    credential_id: int,
    session: AsyncSession,
    youtube_config: YouTubeUploadConfig | None = None,
) -> YouTubeUploader:
    """
    Create YouTubeUploader instance using credentials from database.

    Args:
        credential_id: Database credential ID
        session: Database session
        youtube_config: Optional YouTube config (will use defaults if not provided)

    Returns:
        YouTubeUploader instance configured with database credentials
    """
    # Create default config if not provided
    if not youtube_config:
        youtube_config = YouTubeUploadConfig(
            enabled=True,
            client_secrets_file="",  # Not used with DB credentials
            credentials_file="",  # Not used with DB credentials
        )

    # Create credential provider
    encryption = get_encryption()
    repo = UserCredentialRepository(session)

    credential_provider = DatabaseCredentialProvider(
        credential_id=credential_id,
        encryption_service=encryption,
        credential_repository=repo,
    )

    # Create uploader with credential provider
    uploader = YouTubeUploader(config=youtube_config, credential_provider=credential_provider)

    logger.info(f"Created YouTubeUploader with DB credential ID: {credential_id}")
    return uploader


async def create_vk_uploader_from_db(
    credential_id: int,
    session: AsyncSession,
    vk_config: VKUploadConfig | None = None,
) -> VKUploader:
    """
    Create VKUploader instance using credentials from database.

    Args:
        credential_id: Database credential ID
        session: Database session
        vk_config: Optional VK config (will use defaults if not provided)

    Returns:
        VKUploader instance configured with database credentials
    """
    # Load credential from DB
    encryption = get_encryption()
    repo = UserCredentialRepository(session)

    credential = await repo.get(credential_id)
    if not credential or not credential.encrypted_data:
        raise ValueError(f"Credential {credential_id} not found or empty")

    decrypted = encryption.decrypt_credentials(credential.encrypted_data)
    access_token = decrypted.get("access_token", "")

    if not access_token:
        raise ValueError(f"No access_token found in credential {credential_id}")

    # Create default config if not provided
    if not vk_config:
        vk_config = VKUploadConfig(
            enabled=True,
            access_token=access_token,
        )
    else:
        # Override access_token with one from DB
        vk_config.access_token = access_token

    uploader = VKUploader(config=vk_config)

    logger.info(f"Created VKUploader with DB credential ID: {credential_id}")
    return uploader


async def create_uploader_from_db(
    platform: str,
    credential_id: int,
    session: AsyncSession,
    config: Any | None = None,
) -> YouTubeUploader | VKUploader:
    """
    Create platform uploader from database credentials.

    Args:
        platform: Platform name ('youtube' or 'vk_video')
        credential_id: Database credential ID
        session: Database session
        config: Optional platform config

    Returns:
        Platform uploader instance

    Raises:
        ValueError: If platform is not supported
    """
    if platform == "youtube":
        return await create_youtube_uploader_from_db(credential_id, session, config)
    elif platform in ("vk", "vk_video"):
        return await create_vk_uploader_from_db(credential_id, session, config)
    else:
        raise ValueError(f"Unsupported platform: {platform}")

