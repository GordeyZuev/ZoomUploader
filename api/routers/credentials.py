"""User credentials management endpoints (multi-tenancy)"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_user
from api.auth.encryption import get_encryption
from api.dependencies import get_db_session
from api.repositories.auth_repos import UserCredentialRepository
from api.schemas.auth import UserCredentialCreate, UserCredentialUpdate, UserInDB
from api.schemas.credentials import (
    CredentialCreateRequest,
    CredentialDeleteResponse,
    CredentialResponse,
    CredentialStatusResponse,
    CredentialUpdateRequest,
    VKCredentialsManual,
    YouTubeCredentialsManual,
    ZoomCredentialsManual,
)
from logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/credentials", tags=["Credentials"])


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


@router.get("/status", response_model=CredentialStatusResponse)
async def check_credentials_status(
    current_user: UserInDB = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CredentialStatusResponse:
    cred_repo = UserCredentialRepository(session)

    platforms = ["zoom", "youtube", "vk_video", "fireworks", "deepseek", "openai", "yandex_disk", "google_drive"]

    status_map = {}
    for platform in platforms:
        credentials = await cred_repo.list_by_platform(current_user.id, platform)
        status_map[platform] = len(credentials) > 0

    available_platforms = [p for p, has_creds in status_map.items() if has_creds]

    return CredentialStatusResponse(
        user_id=current_user.id,
        available_platforms=available_platforms,
        credentials_status=status_map,
    )


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

    return CredentialDeleteResponse(message=f"Credential {credential_id} deleted successfully")
