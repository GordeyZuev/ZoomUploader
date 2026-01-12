"""OAuth endpoints for YouTube and VK authorization."""

from urllib.parse import urlencode

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
        from datetime import datetime, timedelta

        # Calculate expiry time for VK token
        expires_in = token_data.get("expires_in", 86400)  # Default 24 hours
        expiry = datetime.utcnow() + timedelta(seconds=expires_in)

        credentials = {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),  # VK ID refresh token
            "user_id": token_data.get("user_id"),
            "expires_in": expires_in,
            "expiry": expiry.isoformat() + "Z",  # ISO format with timezone
        }
    elif platform == "zoom":
        from datetime import datetime, timedelta

        # Calculate expiry time for Zoom token
        expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
        expiry = datetime.utcnow() + timedelta(seconds=expires_in)

        credentials = {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "token_type": token_data.get("token_type", "bearer"),
            "scope": token_data.get("scope", " ".join(config.scopes)),
            "expires_in": expires_in,
            "expiry": expiry.isoformat() + "Z",
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
        # Validate state to get user_id and code_verifier (if PKCE was used)
        metadata = await state_manager.validate_state(state)
        if not metadata:
            raise ValueError("Invalid or expired state token")

        user_id = metadata["user_id"]
        code_verifier = metadata.get("code_verifier")  # For PKCE

        # Exchange code for token
        config = get_platform_config("youtube")
        oauth_service = OAuthService(config, state_manager)
        token_data = await oauth_service.exchange_code_for_token(code, code_verifier=code_verifier)

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


@router.get("/vk/authorize/implicit")
async def vk_authorize_implicit(
    current_user: UserInDB = Depends(get_current_user),
):
    """
    Generate VK Implicit Flow URL (legacy method, no refresh token).

    Uses separate VK app (54249533) configured for Implicit Flow.

    Pros:
    - Works immediately without VK approval
    - Grants video, groups, wall permissions

    Cons:
    - Token expires in 24 hours
    - No refresh token
    - Deprecated by VK (use for testing only)
    """
    # Load VK config to get implicit_flow_app_id
    import os

    from api.services.oauth_platforms import load_oauth_config

    config_path = os.getenv("VK_OAUTH_CONFIG", "config/oauth_vk.json")
    vk_config = load_oauth_config(config_path)

    # Use separate app_id for Implicit Flow (legacy VK app)
    implicit_app_id = vk_config.get("implicit_flow_app_id", "54249533")

    params = {
        "client_id": implicit_app_id,
        "display": "page",
        "redirect_uri": "https://oauth.vk.com/blank.html",
        "scope": "video,groups,wall",
        "response_type": "token",
        "v": "5.131",
    }

    implicit_url = f"https://oauth.vk.com/authorize?{urlencode(params)}"

    logger.info(f"VK Implicit Flow URL generated: user_id={current_user.id} app_id={implicit_app_id}")

    return {
        "method": "implicit_flow",
        "app_id": implicit_app_id,
        "authorization_url": implicit_url,
        "instructions": [
            "1. Open authorization_url in browser",
            "2. Allow app permissions (video, groups, wall)",
            "3. Copy access_token from redirected URL",
            "4. POST to /api/v1/credentials/ with platform=vk_video",
        ],
        "example_credentials": {
            "platform": "vk_video",
            "account_name": "vk_manual",
            "credentials": {
                "access_token": "YOUR_COPIED_TOKEN",
                "user_id": 123456,
            },
        },
        "note": "Token expires in ~24h. No auto-refresh. Use VK ID OAuth for production.",
    }


@router.get("/vk/callback")
async def vk_callback(
    code: str = Query(..., description="Authorization code from VK"),
    state: str = Query(..., description="State token for CSRF protection"),
    device_id: str | None = Query(None, description="Device ID from VK (required for VK ID)"),
    error: str | None = Query(None, description="Error from OAuth provider"),
    session: AsyncSession = Depends(get_db_session),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """Handle VK OAuth callback with VK ID support."""
    base_redirect = "http://localhost:8080"

    if error:
        logger.error(f"VK OAuth error: {error}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error={error}")

    try:
        # Validate state to get user_id and code_verifier (for PKCE)
        metadata = await state_manager.validate_state(state)
        if not metadata:
            raise ValueError("Invalid or expired state token")

        user_id = metadata["user_id"]
        code_verifier = metadata.get("code_verifier")  # VK ID requires PKCE

        # Exchange code for token (VK ID requires device_id)
        config = get_platform_config("vk_video")
        oauth_service = OAuthService(config, state_manager)
        token_data = await oauth_service.exchange_code_for_token(
            code,
            code_verifier=code_verifier,
            device_id=device_id
        )

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


@router.get("/zoom/authorize")
async def zoom_authorize(
    request: Request,
    current_user: UserInDB = Depends(get_current_user),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """
    Initiate Zoom OAuth flow.

    Returns authorization URL for user to visit.
    """
    try:
        config = get_platform_config("zoom")
        oauth_service = OAuthService(config, state_manager)

        ip_address = request.client.host if request.client else None
        result = await oauth_service.get_authorization_url(current_user.id, ip_address)

        logger.info(f"Zoom OAuth initiated: user_id={current_user.id}")
        return result

    except Exception as e:
        logger.error(f"Zoom OAuth authorization failed: user_id={current_user.id} error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate authorization URL",
        )


@router.get("/zoom/callback")
async def zoom_callback(
    code: str = Query(..., description="Authorization code from Zoom"),
    state: str = Query(..., description="State token for CSRF protection"),
    error: str | None = Query(None, description="Error from OAuth provider"),
    session: AsyncSession = Depends(get_db_session),
    state_manager: OAuthStateManager = Depends(get_state_manager),
):
    """
    Handle Zoom OAuth callback.

    Exchanges code for token and saves to database.
    """
    base_redirect = "http://localhost:8080"

    if error:
        logger.error(f"Zoom OAuth error: {error}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error={error}")

    try:
        # Validate state to get user_id
        metadata = await state_manager.validate_state(state)
        if not metadata:
            raise ValueError("Invalid or expired state token")

        user_id = metadata["user_id"]

        # Exchange code for token
        config = get_platform_config("zoom")
        oauth_service = OAuthService(config, state_manager)
        token_data = await oauth_service.exchange_code_for_token(code)

        # Validate token
        token_valid = await oauth_service.validate_token(token_data["access_token"])
        if not token_valid:
            logger.warning(f"Zoom token validation failed after exchange: user_id={user_id}")

        # Save credentials
        await save_oauth_credentials(user_id, "zoom", token_data, config, session)

        logger.info(f"Zoom OAuth completed successfully: user_id={user_id}")
        return RedirectResponse(url=f"{base_redirect}/settings/platforms?oauth_success=true&platform=zoom")

    except ValueError as e:
        logger.error(f"Zoom OAuth callback error: {e}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error=invalid_state")
    except Exception as e:
        logger.error(f"Zoom OAuth callback failed: {e}")
        return RedirectResponse(url=f"{base_redirect}/?oauth_error=token_exchange_failed")
