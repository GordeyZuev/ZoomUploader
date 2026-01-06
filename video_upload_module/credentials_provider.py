"""Credential provider for accessing platform credentials from database or files."""

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials

from logger import get_logger

logger = get_logger()


class CredentialProvider(ABC):
    """Abstract base class for credential providers."""

    @abstractmethod
    async def load_credentials(self) -> dict[str, Any] | None:
        """Load credentials data."""
        pass

    @abstractmethod
    async def save_credentials(self, credentials_data: dict[str, Any]) -> bool:
        """Save credentials data."""
        pass

    @abstractmethod
    async def get_google_credentials(self, scopes: list[str]) -> Credentials | None:
        """Get Google OAuth2 Credentials object."""
        pass

    @abstractmethod
    async def update_google_credentials(self, credentials: Credentials) -> bool:
        """Update Google OAuth2 credentials after refresh."""
        pass


class FileCredentialProvider(CredentialProvider):
    """Credential provider that uses file system."""

    def __init__(self, credentials_file: str):
        self.credentials_file = credentials_file

    async def load_credentials(self) -> dict[str, Any] | None:
        """Load credentials from file."""
        path = Path(self.credentials_file)
        if not path.exists():
            return None

        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load credentials from {self.credentials_file}: {e}")
            return None

    async def save_credentials(self, credentials_data: dict[str, Any]) -> bool:
        """Save credentials to file."""
        try:
            with open(self.credentials_file, "w", encoding="utf-8") as f:
                json.dump(credentials_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save credentials to {self.credentials_file}: {e}")
            return False

    async def get_google_credentials(self, scopes: list[str]) -> Credentials | None:
        """Get Google OAuth2 Credentials from file."""
        data = await self.load_credentials()
        if not data:
            return None

        try:
            # Try loading from "token" key (bundle format)
            if isinstance(data, dict) and "token" in data:
                return Credentials.from_authorized_user_info(data["token"], scopes)
            # Try loading directly (simple format)
            else:
                return Credentials.from_authorized_user_info(data, scopes)
        except Exception as e:
            logger.warning(f"Failed to parse credentials from file: {e}")
            return None

    async def update_google_credentials(self, credentials: Credentials) -> bool:
        """Update Google credentials in file after refresh."""
        try:
            data = await self.load_credentials()
            token_data = json.loads(credentials.to_json())

            if isinstance(data, dict) and "token" in data:
                # Bundle format - update token section
                data["token"] = token_data
            else:
                # Simple format - replace entire file
                data = token_data

            return await self.save_credentials(data)
        except Exception as e:
            logger.error(f"Failed to update credentials in file: {e}")
            return False


class DatabaseCredentialProvider(CredentialProvider):
    """Credential provider that uses database."""

    def __init__(
        self,
        credential_id: int,
        encryption_service: Any,
        credential_repository: Any,
    ):
        self.credential_id = credential_id
        self.encryption = encryption_service
        self.repo = credential_repository

    async def load_credentials(self) -> dict[str, Any] | None:
        """Load credentials from database."""
        try:
            credential = await self.repo.get(self.credential_id)
            if not credential or not credential.encrypted_data:
                logger.warning(f"Credential {self.credential_id} not found or empty")
                return None

            decrypted = self.encryption.decrypt_credentials(credential.encrypted_data)
            return decrypted
        except Exception as e:
            logger.error(f"Failed to load credential {self.credential_id} from DB: {e}")
            return None

    async def save_credentials(self, credentials_data: dict[str, Any]) -> bool:
        """Save credentials to database."""
        try:
            from api.schemas.auth import UserCredentialUpdate

            encrypted = self.encryption.encrypt_credentials(credentials_data)
            update_data = UserCredentialUpdate(encrypted_data=encrypted)
            await self.repo.update(self.credential_id, update_data)
            logger.info(f"Updated credential {self.credential_id} in database")
            return True
        except Exception as e:
            logger.error(f"Failed to save credential {self.credential_id} to DB: {e}")
            return False

    async def get_google_credentials(self, scopes: list[str]) -> Credentials | None:
        """Get Google OAuth2 Credentials from database."""
        data = await self.load_credentials()
        if not data:
            return None

        try:
            # Extract token section from bundled format
            if isinstance(data, dict) and "token" in data:
                token_data = data["token"]
            else:
                token_data = data

            # Create Credentials object
            return Credentials.from_authorized_user_info(token_data, scopes)
        except Exception as e:
            logger.error(f"Failed to create Google credentials from DB data: {e}")
            return None

    async def update_google_credentials(self, credentials: Credentials) -> bool:
        """Update Google credentials in database after refresh."""
        try:
            # Load existing data
            data = await self.load_credentials()
            if not data:
                logger.error("Cannot update - no existing credentials found")
                return False

            # Update token section
            token_data = json.loads(credentials.to_json())

            if isinstance(data, dict) and "token" in data:
                # Bundle format - update token section only
                data["token"] = token_data
            else:
                # Simple format - replace entire structure
                data = token_data

            # Save back to database
            return await self.save_credentials(data)
        except Exception as e:
            logger.error(f"Failed to update Google credentials in DB: {e}")
            return False


def create_credential_provider(
    credential_id: int | None = None,
    credentials_file: str | None = None,
    encryption_service: Any = None,
    credential_repository: Any = None,
) -> CredentialProvider:
    """
    Factory function to create appropriate credential provider.

    Args:
        credential_id: Database credential ID (if using DB)
        credentials_file: File path (if using file system)
        encryption_service: Encryption service (required for DB)
        credential_repository: Credential repository (required for DB)

    Returns:
        CredentialProvider instance

    Raises:
        ValueError: If parameters are invalid
    """
    if credential_id is not None:
        if not encryption_service or not credential_repository:
            raise ValueError("encryption_service and credential_repository required for DB provider")
        return DatabaseCredentialProvider(credential_id, encryption_service, credential_repository)
    elif credentials_file:
        return FileCredentialProvider(credentials_file)
    else:
        raise ValueError("Either credential_id or credentials_file must be provided")

