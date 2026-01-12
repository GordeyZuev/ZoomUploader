"""Endpoints для управления учетными данными пользователей (multi-tenancy)."""

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_user
from api.auth.encryption import get_encryption
from api.dependencies import get_db_session
from api.repositories.auth_repos import UserCredentialRepository
from api.schemas.auth import UserCredentialCreate, UserCredentialUpdate, UserInDB
from api.schemas.credentials import VKCredentialsManual, YouTubeCredentialsManual, ZoomCredentialsManual
from api.services.vk_token_service import VKTokenService
from logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/credentials", tags=["Credentials"])


class CredentialCreateRequest(BaseModel):
    """Запрос на создание учетных данных."""

    platform: str = Field(..., description="Платформа (zoom, youtube, vk)")
    account_name: str | None = Field(None, description="Имя аккаунта (для нескольких аккаунтов)")
    credentials: dict = Field(..., description="Учетные данные платформы")


class CredentialUpdateRequest(BaseModel):
    """Запрос на обновление учетных данных."""

    credentials: dict = Field(..., description="Обновленные учетные данные")


class CredentialResponse(BaseModel):
    """Ответ с информацией об учетных данных."""

    id: int = Field(..., description="ID учетных данных")
    platform: str = Field(..., description="Платформа")
    account_name: str | None = Field(None, description="Имя аккаунта")
    is_active: bool = Field(..., description="Активны ли учетные данные")
    last_used_at: str | None = Field(None, description="Время последнего использования")
    credentials: dict | None = Field(None, description="Учетные данные (только при запросе с флагом include_data)")


@router.get("/", response_model=list[CredentialResponse])
async def list_credentials(
    platform: str | None = None,
    include_data: bool = False,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Получить список учетных данных пользователя.

    Args:
        platform: Фильтр по платформе (опционально)
        include_data: Включить расшифрованные credentials в ответ
        current_user: Текущий пользователь
        session: Database session

    Returns:
        Список учетных данных
    """
    cred_repo = UserCredentialRepository(session)

    if platform:
        # Если указана платформа - возвращаем только для нее
        credentials = await cred_repo.list_by_platform(current_user.id, platform)
    else:
        # Иначе - все credentials пользователя
        credentials = await cred_repo.find_by_user(current_user.id)

    result = []
    encryption = get_encryption() if include_data else None

    for cred in credentials:
        response = CredentialResponse(
            id=cred.id,
            platform=cred.platform,
            account_name=cred.account_name,
            is_active=cred.is_active,
            last_used_at=cred.last_used_at.isoformat() if cred.last_used_at else None,
        )

        if include_data and encryption:
            try:
                decrypted_data = encryption.decrypt_credentials(cred.encrypted_data)
                response.credentials = decrypted_data
            except Exception as e:
                logger.error(f"Failed to decrypt credentials for id={cred.id}: {e}")
                # Продолжаем со следующим credential

        result.append(response)

    return result


@router.get("/status")
async def check_credentials_status(
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    cred_repo = UserCredentialRepository(session)

    platforms = ["zoom", "youtube", "vk_video", "fireworks", "deepseek", "openai", "yandex_disk", "google_drive"]

    status_map = {}
    for platform in platforms:
        credentials = await cred_repo.list_by_platform(current_user.id, platform)
        status_map[platform] = len(credentials) > 0

    available_platforms = [p for p, has_creds in status_map.items() if has_creds]

    return {
        "user_id": current_user.id,
        "available_platforms": available_platforms,
        "credentials_status": status_map,
    }


@router.get("/{credential_id}", response_model=CredentialResponse)
async def get_credential_by_id(
    credential_id: int,
    include_data: bool = False,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Получить конкретный credential по ID.

    Args:
        credential_id: ID credential
        include_data: Включить расшифрованные данные в ответ
        current_user: Текущий пользователь
        session: Database session

    Returns:
        Credential

    Raises:
        HTTPException: Если credential не найден
    """
    cred_repo = UserCredentialRepository(session)
    credential = await cred_repo.get_by_id(credential_id)

    if not credential or credential.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    response = CredentialResponse(
        id=credential.id,
        platform=credential.platform,
        account_name=credential.account_name,
        is_active=credential.is_active,
        last_used_at=credential.last_used_at.isoformat() if credential.last_used_at else None,
    )

    if include_data:
        encryption = get_encryption()
        try:
            decrypted_data = encryption.decrypt_credentials(credential.encrypted_data)
            response.credentials = decrypted_data
        except Exception as e:
            logger.error(f"Failed to decrypt credentials: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt credentials",
            )

    return response


def _validate_credentials(platform: str, credentials: dict[str, Any]) -> None:
    """Validate credentials structure based on platform."""
    try:
        if platform == "youtube":
            YouTubeCredentialsManual(**credentials)
        elif platform in ("vk", "vk_video"):
            VKCredentialsManual(**credentials)
        elif platform == "zoom":
            ZoomCredentialsManual(**credentials)
        # Other platforms don't have specific validation yet
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_messages.append(f"{field}: {message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {platform} credentials: {'; '.join(error_messages)}",
        ) from e


@router.post("/", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credentials(
    request: CredentialCreateRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Создать учетные данные для платформы.

    Args:
        request: Данные для создания
        current_user: Текущий пользователь
        session: Database session

    Returns:
        Созданные учетные данные

    Raises:
        HTTPException: Если учетные данные уже существуют или невалидны
    """
    # Validate credentials structure
    _validate_credentials(request.platform, request.credentials)

    cred_repo = UserCredentialRepository(session)

    # Извлекаем account_name из credentials если не указан явно
    account_name = request.account_name
    if not account_name:
        # Для Zoom и других платформ пытаемся взять из поля "account"
        if "account" in request.credentials:
            account_name = request.credentials["account"]
            logger.info(f"Auto-extracted account_name from credentials: {account_name}")
        # Для VK можно использовать другую логику
        elif request.platform == "vk" and "group_id" in request.credentials:
            account_name = f"group_{request.credentials['group_id']}"

    # Проверяем существование по (platform, account_name)
    if account_name:
        existing = await cred_repo.get_by_platform(current_user.id, request.platform, account_name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Credentials for platform '{request.platform}' with account '{account_name}' already exist",
            )

    # Проверяем на дубликаты по содержимому credentials
    encryption = get_encryption()
    try:
        encrypted_data = encryption.encrypt_credentials(request.credentials)
    except Exception as e:
        logger.error(f"Failed to encrypt credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encrypt credentials",
        )

    # Проверяем что такие же credentials не существуют
    all_platform_creds = await cred_repo.list_by_platform(current_user.id, request.platform)
    for existing_cred in all_platform_creds:
        try:
            existing_decrypted = encryption.decrypt_credentials(existing_cred.encrypted_data)
            # Сравниваем ключевые поля
            if request.platform == "zoom":
                if (
                    existing_decrypted.get("account_id") == request.credentials.get("account_id")
                    and existing_decrypted.get("client_id") == request.credentials.get("client_id")
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Credentials with same account_id and client_id already exist "
                        f"(credential_id: {existing_cred.id}, account: {existing_cred.account_name})",
                    )
            elif request.platform == "youtube":
                existing_client_id = (
                    existing_decrypted.get("client_secrets", {}).get("installed", {}).get("client_id")
                )
                new_client_id = request.credentials.get("client_secrets", {}).get("installed", {}).get("client_id")
                if existing_client_id and existing_client_id == new_client_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Credentials with same client_id already exist (credential_id: {existing_cred.id})",
                    )
            elif request.platform == "vk":
                if existing_decrypted.get("access_token") == request.credentials.get("access_token"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Credentials with same access_token already exist (credential_id: {existing_cred.id})",
                    )
        except Exception as e:
            # Если не можем расшифровать - пропускаем
            logger.warning(f"Failed to decrypt existing credential {existing_cred.id}: {e}")
            continue

    cred_create = UserCredentialCreate(
        user_id=current_user.id,
        platform=request.platform,
        account_name=account_name,
        encrypted_data=encrypted_data,
    )
    credential = await cred_repo.create(credential_data=cred_create)

    account_log = f" | account={account_name}" if account_name else ""
    logger.info(f"User credentials created: user_id={current_user.id} | platform={request.platform}{account_log}")

    return CredentialResponse(
        id=credential.id,
        platform=credential.platform,
        account_name=credential.account_name,
        is_active=credential.is_active,
        last_used_at=None,
    )


@router.patch("/{credential_id}", response_model=CredentialResponse)
async def update_credentials(
    credential_id: int,
    request: CredentialUpdateRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Обновить учетные данные.

    Используется PATCH для частичного обновления (только encrypted_data).

    Args:
        credential_id: ID credential
        request: Новые данные
        current_user: Текущий пользователь
        session: Database session

    Returns:
        Обновленные учетные данные

    Raises:
        HTTPException: Если учетные данные не найдены
    """
    cred_repo = UserCredentialRepository(session)

    credential = await cred_repo.get_by_id(credential_id)
    if not credential or credential.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    encryption = get_encryption()
    try:
        encrypted_data = encryption.encrypt_credentials(request.credentials)
    except Exception as e:
        logger.error(f"Failed to encrypt credentials: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encrypt credentials",
        )

    cred_update = UserCredentialUpdate(encrypted_data=encrypted_data)
    updated_credential = await cred_repo.update(credential.id, credential_data=cred_update)

    logger.info(f"User credentials updated: user_id={current_user.id} | credential_id={credential_id}")

    return CredentialResponse(
        id=updated_credential.id,
        platform=updated_credential.platform,
        account_name=updated_credential.account_name,
        is_active=updated_credential.is_active,
        last_used_at=(updated_credential.last_used_at.isoformat() if updated_credential.last_used_at else None),
    )


@router.delete("/{credential_id}")
async def delete_credentials(
    credential_id: int,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Удалить учетные данные.

    Args:
        credential_id: ID credential
        current_user: Текущий пользователь
        session: Database session

    Returns:
        Подтверждение удаления

    Raises:
        HTTPException: Если учетные данные не найдены
    """
    cred_repo = UserCredentialRepository(session)

    credential = await cred_repo.get_by_id(credential_id)
    if not credential or credential.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    await cred_repo.delete(credential.id)

    logger.info(f"User credentials deleted: user_id={current_user.id} | credential_id={credential_id}")

    return {"message": f"Credential {credential_id} deleted successfully"}


# ========================================
# VK Token Management (Implicit Flow)
# ========================================


class VKTokenSubmitRequest(BaseModel):
    """Request to submit VK access token - accepts URL or token string."""

    token_data: str = Field(
        ...,
        min_length=10,
        description="VK token: full URL from browser OR just access_token string",
        examples=[
            "https://oauth.vk.com/blank.html#access_token=vk1.a.ABC123...&expires_in=86400&user_id=123456",
            "vk1.a.ABC123...",
        ],
    )
    account_name: str | None = Field(None, description="Account name for identification")


class VKTokenSubmitResponse(BaseModel):
    """Response after submitting VK token."""

    success: bool = Field(..., description="Whether token was saved successfully")
    credential_id: int | None = Field(None, description="ID of created/updated credential")
    user_id: int | None = Field(None, description="VK user_id")
    expiry: str | None = Field(None, description="Token expiry time (ISO format)")
    message: str = Field(..., description="Result message")


class VKTokenStatusResponse(BaseModel):
    """Response with VK credential status."""

    credential_id: int = Field(..., description="Credential ID")
    status: str = Field(
        ...,
        description="Token status: 'valid', 'expiring_soon' (<2h), 'expired', 'no_expiry_info'",
    )
    is_valid: bool | None = Field(None, description="Whether token is still valid (not expired)")
    expiry: str | None = Field(None, description="Token expiry time (ISO format)")
    time_until_expiry: str | None = Field(None, description="Human-readable time until expiry")
    needs_refresh: bool = Field(..., description="Whether token needs to be refreshed")


def parse_vk_token_data(token_data: str) -> dict:
    """
    Parse VK token from URL or raw token string.

    Accepts:
    1. Full URL: https://oauth.vk.com/blank.html#access_token=...&expires_in=86400&user_id=123456
    2. Fragment: access_token=...&expires_in=86400&user_id=123456
    3. Raw token: vk1.a.ABC123...

    Returns:
        dict with access_token, expires_in (optional), user_id (optional)
    """
    token_data = token_data.strip()

    # Case 1: Full URL
    if token_data.startswith("http"):
        parsed = urlparse(token_data)
        # Fragment contains the data after #
        fragment = parsed.fragment
        if fragment:
            params = parse_qs(fragment)
            return {
                "access_token": params.get("access_token", [None])[0],
                "expires_in": int(params.get("expires_in", [86400])[0]),
                "user_id": int(params["user_id"][0]) if "user_id" in params else None,
            }

    # Case 2: Fragment only (access_token=...&expires_in=...)
    if "access_token=" in token_data:
        # Remove leading # if present
        if token_data.startswith("#"):
            token_data = token_data[1:]

        params = parse_qs(token_data)
        return {
            "access_token": params.get("access_token", [None])[0],
            "expires_in": int(params.get("expires_in", [86400])[0]),
            "user_id": int(params["user_id"][0]) if "user_id" in params else None,
        }

    # Case 3: Raw token (starts with vk1.a. or similar)
    if token_data.startswith("vk"):
        return {
            "access_token": token_data,
            "expires_in": 86400,  # Default 24h
            "user_id": None,
        }

    raise ValueError("Invalid token format. Expected: URL, fragment, or raw token starting with 'vk'")


@router.post("/vk", response_model=VKTokenSubmitResponse)
async def submit_vk_token(
    request: VKTokenSubmitRequest,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Create VK access token (Implicit Flow).

    Accepts:
    - Full URL from browser: https://oauth.vk.com/blank.html#access_token=...
    - Just the access_token: vk1.a.ABC123...

    This endpoint:
    1. Parses token from URL or string
    2. Validates token via VK API
    3. Auto-detects user_id
    4. Saves/updates credentials with expiry
    5. Handles IP mismatch errors

    Note: VK Implicit Flow tokens expire in ~24 hours and cannot be refreshed.
    """
    vk_service = VKTokenService()

    # Parse token data
    try:
        parsed = parse_vk_token_data(request.token_data)
        access_token = parsed["access_token"]
        expires_in = parsed["expires_in"]
        vk_user_id_from_url = parsed.get("user_id")

        if not access_token:
            raise ValueError("access_token not found in provided data")

    except Exception as e:
        logger.error(f"Failed to parse VK token data: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid token format: {str(e)}",
        )

    # Validate token
    logger.info(f"Validating VK token for user_id={current_user.id}")
    is_valid, error_type, user_data = await vk_service.validate_token(access_token)

    if not is_valid:
        error_info = vk_service.get_error_message(error_type)
        logger.warning(f"VK token validation failed: user_id={current_user.id} error={error_type}")

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": error_info["error"],
                "message": error_info["message"],
                "solution": error_info.get("solution"),
                "error_type": error_type,
            },
        )

    # Extract user_id (from URL, API, or both)
    vk_user_id = vk_user_id_from_url or (user_data.get("id") if user_data else None)
    if not vk_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to determine VK user_id",
        )

    # Calculate expiry
    expiry = vk_service.calculate_expiry(expires_in)
    expiry_iso = vk_service.format_expiry_iso(expiry)

    # Prepare credentials
    credentials_data = {
        "access_token": access_token,
        "user_id": vk_user_id,
        "expires_in": expires_in,
        "expiry": expiry_iso,
    }

    # Check if credentials already exist
    cred_repo = UserCredentialRepository(session)
    encryption = get_encryption()

    account_name = request.account_name or f"vk_{vk_user_id}"
    existing_cred = await cred_repo.get_by_platform(current_user.id, "vk_video", account_name)

    if existing_cred:
        # Update existing credentials
        encrypted_data = encryption.encrypt_credentials(credentials_data)
        cred_update = UserCredentialUpdate(encrypted_data=encrypted_data, is_active=True)
        updated = await cred_repo.update(existing_cred.id, credential_data=cred_update)

        logger.info(
            f"VK credentials updated: user_id={current_user.id} "
            f"credential_id={updated.id} vk_user_id={vk_user_id} expiry={expiry_iso}"
        )

        return VKTokenSubmitResponse(
            success=True,
            credential_id=updated.id,
            user_id=vk_user_id,
            expiry=expiry_iso,
            message=f"VK token updated successfully (expires in {expires_in // 3600}h)",
        )

    # Create new credentials
    encrypted_data = encryption.encrypt_credentials(credentials_data)
    cred_create = UserCredentialCreate(
        user_id=current_user.id,
        platform="vk_video",
        account_name=account_name,
        encrypted_data=encrypted_data,
    )
    credential = await cred_repo.create(credential_data=cred_create)

    logger.info(
        f"VK credentials created: user_id={current_user.id} "
        f"credential_id={credential.id} vk_user_id={vk_user_id} expiry={expiry_iso}"
    )

    return VKTokenSubmitResponse(
        success=True,
        credential_id=credential.id,
        user_id=vk_user_id,
        expiry=expiry_iso,
        message=f"VK token saved successfully (expires in {expires_in // 3600}h)",
    )


@router.get("/vk/{credential_id}/status", response_model=VKTokenStatusResponse)
async def get_vk_credential_status(
    credential_id: int,
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Check VK credential status by ID.

    Checks expiry from database (no VK API call).
    Validation through VK API happens only during token submission (POST /vk/).

    Returns:
    - Whether token is valid (not expired)
    - Token expiry time
    - Whether token needs refresh (< 2 hours until expiry)
    """
    cred_repo = UserCredentialRepository(session)
    credential = await cred_repo.get_by_id(credential_id)

    if not credential or credential.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Credential {credential_id} not found",
        )

    if credential.platform != "vk_video":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential {credential_id} is not a VK credential (platform: {credential.platform})",
        )

    latest_cred = credential

    # Decrypt to get expiry
    encryption = get_encryption()
    try:
        cred_data = encryption.decrypt_credentials(latest_cred.encrypted_data)
        expiry_str = cred_data.get("expiry")

        if not expiry_str:
            # No expiry information (old credential format)
            logger.warning(f"VK credential {latest_cred.id} has no expiry information")
            return VKTokenStatusResponse(
                credential_id=latest_cred.id,
                status="no_expiry_info",
                is_valid=None,
                expiry=None,
                time_until_expiry=None,
                needs_refresh=True,
            )

        # Parse expiry
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        is_valid = expiry > now
        time_left = expiry - now
        time_left_seconds = time_left.total_seconds()

        # Format time until expiry
        if time_left_seconds > 0:
            hours = int(time_left_seconds // 3600)
            minutes = int((time_left_seconds % 3600) // 60)
            time_until_expiry = f"{hours}h {minutes}m"
        else:
            time_until_expiry = "expired"

        # Determine status
        if not is_valid:
            status_value = "expired"
            needs_refresh = True
        elif time_left_seconds < 7200:  # < 2 hours
            status_value = "expiring_soon"
            needs_refresh = True
        else:
            status_value = "valid"
            needs_refresh = False

        return VKTokenStatusResponse(
            credential_id=latest_cred.id,
            status=status_value,
            is_valid=is_valid,
            expiry=expiry_str,
            time_until_expiry=time_until_expiry,
            needs_refresh=needs_refresh,
        )

    except Exception as e:
        logger.error(f"Failed to decrypt VK credential {latest_cred.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read credential data: {str(e)}",
        )
