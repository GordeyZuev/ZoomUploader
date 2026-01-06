"""OAuth endpoints for YouTube and VK authorization."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_user
from api.auth.encryption import get_encryption
from api.dependencies import get_db_session, get_redis
from api.repositories.auth_repos import UserCredentialRepository
from api.schemas.auth import UserCredentialCreate, UserInDB
from api.services.oauth_platforms import OAuthPlatformConfig, get_platform_config
from api.services.oauth_service import OAuthService
from api.services.oauth_state import OAuthStateManager
from logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/oauth", tags=["OAuth"])


def get_state_manager(redis=Depends(get_redis)) -> OAuthStateManager:
    """Dependency to get OAuth state manager."""
    return OAuthStateManager(redis)


async def save_oauth_credentials(
    user_id: int,
    platform: str,
    token_data: dict,
    config: OAuthPlatformConfig,
    session: AsyncSession,
) -> int:
    """Save OAuth credentials to database."""
    encryption = get_encryption()
    cred_repo = UserCredentialRepository(session)

    if platform == "youtube":
        from datetime import datetime, timedelta

        # Calculate expiry time
        expires_in = token_data.get("expires_in", 3600)
        expiry = datetime.utcnow() + timedelta(seconds=expires_in)

        credentials = {
            "client_secrets": {
                "web": {
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "project_id": "zoomuploader",
                    "auth_uri": config.authorization_url,
                    "token_uri": config.token_url,
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [config.redirect_uri],
                }
            },
            "token": {
                "token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "token_uri": config.token_url,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "scopes": config.scopes,
                "expiry": expiry.isoformat() + "Z",
            },
        }
    elif platform == "vk_video":
        credentials = {
            "access_token": token_data["access_token"],
            "user_id": token_data.get("user_id"),
            "expires_in": token_data.get("expires_in"),
        }
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    encrypted_data = encryption.encrypt_credentials(credentials)

    cred_create = UserCredentialCreate(
        user_id=user_id,
        platform=platform,
        account_name="oauth_auto",
        encrypted_data=encrypted_data,
    )

    credential = await cred_repo.create(credential_data=cred_create)
    logger.info(f"OAuth credentials saved: user_id={user_id} platform={platform} credential_id={credential.id}")

    return credential.id


@router.get("/youtube/authorize")
async def youtube_authorize(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """
    Initiate YouTube OAuth flow.

    Returns authorization URL for user to visit.
    """
    try:
        config = get_platform_config("youtube")
        oauth_service = OAuthService(config, state_manager)

        ip_address = request.client.host if request.client else None
        result = await oauth_service.get_authorization_url(current_user.id, ip_address)

        logger.info(f"YouTube OAuth initiated: user_id={current_user.id}")
        return result

    except Exception as e:
        logger.error(f"YouTube OAuth authorization failed: user_id={current_user.id} error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate authorization URL",
        )


@router.get("/youtube/callback")
async def youtube_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State token for CSRF protection"),
    error: str | None = Query(None, description="Error from OAuth provider"),
    session: AsyncSession = Depends(get_db_session),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """
    Handle YouTube OAuth callback.

    Exchanges code for token and saves to database.
    """
    base_redirect = "http://localhost:8080"

    if error:
        logger.error(f"YouTube OAuth error: {error}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error={error}")

    try:
        # Validate state to get user_id
        metadata = await state_manager.validate_state(state)
        if not metadata:
            raise ValueError("Invalid or expired state token")

        user_id = metadata["user_id"]

        # Exchange code for token
        config = get_platform_config("youtube")
        oauth_service = OAuthService(config, state_manager)
        token_data = await oauth_service.exchange_code_for_token(code)

        # Validate token
        token_valid = await oauth_service.validate_token(token_data["access_token"])
        if not token_valid:
            logger.warning(f"YouTube token validation failed after exchange: user_id={user_id}")

        # Save credentials
        await save_oauth_credentials(user_id, "youtube", token_data, config, session)

        logger.info(f"YouTube OAuth completed successfully: user_id={user_id}")
        return RedirectResponse(url=f"{base_redirect}/settings/platforms?oauth_success=true&platform=youtube")

    except ValueError as e:
        logger.error(f"YouTube OAuth callback error: {e}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error=invalid_state")
    except Exception as e:
        logger.error(f"YouTube OAuth callback failed: {e}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error=token_exchange_failed")


@router.get("/vk/authorize")
async def vk_authorize(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """Initiate VK OAuth flow."""
    try:
        config = get_platform_config("vk_video")
        oauth_service = OAuthService(config, state_manager)

        ip_address = request.client.host if request.client else None
        result = await oauth_service.get_authorization_url(current_user.id, ip_address)

        logger.info(f"VK OAuth initiated: user_id={current_user.id}")
        return result

    except Exception as e:
        logger.error(f"VK OAuth authorization failed: user_id={current_user.id} error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate authorization URL",
        )


@router.get("/vk/callback")
async def vk_callback(
    code: str = Query(..., description="Authorization code from VK"),
    state: str = Query(..., description="State token for CSRF protection"),
    error: str | None = Query(None, description="Error from OAuth provider"),
    session: AsyncSession = Depends(get_db_session),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """Handle VK OAuth callback."""
    base_redirect = "http://localhost:8080"

    if error:
        logger.error(f"VK OAuth error: {error}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error={error}")

    try:
        # Validate state to get user_id
        metadata = await state_manager.validate_state(state)
        if not metadata:
            raise ValueError("Invalid or expired state token")

        user_id = metadata["user_id"]

        # Exchange code for token
        config = get_platform_config("vk_video")
        oauth_service = OAuthService(config, state_manager)
        token_data = await oauth_service.exchange_code_for_token(code)

        # Validate token
        token_valid = await oauth_service.validate_token(token_data["access_token"])
        if not token_valid:
            logger.warning(f"VK token validation failed after exchange: user_id={user_id}")

        # Save credentials
        await save_oauth_credentials(user_id, "vk_video", token_data, config, session)

        logger.info(f"VK OAuth completed successfully: user_id={user_id}")
        return RedirectResponse(url=f"{base_redirect}/settings/platforms?oauth_success=true&platform=vk")

    except ValueError as e:
        logger.error(f"VK OAuth callback error: {e}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error=invalid_state")
    except Exception as e:
        logger.error(f"VK OAuth callback failed: {e}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error=token_exchange_failed")
