"""Утилиты для шифрования учетных данных пользователей."""

import base64
import json

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from api.config import get_settings

settings = get_settings()


class CredentialEncryption:
    """Шифрование учетных данных пользователей."""

    def __init__(self):
        """Инициализация шифрования."""
        # Используем JWT secret как базовый ключ для шифрования
        # В production лучше использовать отдельный ключ
        self._fernet = self._create_fernet(settings.jwt_secret_key)

    def _create_fernet(self, secret: str) -> Fernet:
        """
        Создание Fernet инстанса из секретного ключа.

        Args:
            secret: Секретный ключ

        Returns:
            Fernet инстанс
        """
        # Генерируем ключ из секрета с помощью PBKDF2HMAC
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"zoom_publishing_salt",  # В production использовать случайный salt
            iterations=100000,
            backend=default_backend(),
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        return Fernet(key)

    def encrypt_credentials(self, credentials: dict) -> str:
        """
        Шифрование учетных данных.

        Args:
            credentials: Словарь с учетными данными

        Returns:
            Зашифрованная строка
        """
        json_data = json.dumps(credentials)
        encrypted = self._fernet.encrypt(json_data.encode())
        return encrypted.decode()

    def decrypt_credentials(self, encrypted_data: str) -> dict:
        """
        Расшифровка учетных данных.

        Args:
            encrypted_data: Зашифрованная строка

        Returns:
            Словарь с учетными данными
        """
        decrypted = self._fernet.decrypt(encrypted_data.encode())
        return json.loads(decrypted.decode())


# Singleton инстанс
_encryption = None


def get_encryption() -> CredentialEncryption:
    """
    Получить singleton инстанс шифрования.

    Returns:
        CredentialEncryption инстанс
    """
    global _encryption
    if _encryption is None:
        _encryption = CredentialEncryption()
    return _encryption
