"""Утилиты для безопасности: хеширование паролей, JWT токены."""

from datetime import datetime, timedelta
from typing import Any

import bcrypt
import jwt

from api.config import get_settings

settings = get_settings()


class PasswordHelper:
    """Помощник для работы с паролями."""

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Хеширование пароля с помощью bcrypt.

        Args:
            password: Пароль в открытом виде

        Returns:
            Хешированный пароль
        """
        salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Проверка пароля.

        Args:
            plain_password: Пароль в открытом виде
            hashed_password: Хешированный пароль

        Returns:
            True если пароль совпадает, иначе False
        """
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except Exception:
            return False


class JWTHelper:
    """Помощник для работы с JWT токенами."""

    @staticmethod
    def create_access_token(subject: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        """
        Создание access токена.

        Args:
            subject: Данные для кодирования в токен (обычно {"user_id": 123})
            expires_delta: Время жизни токена (по умолчанию из настроек)

        Returns:
            JWT токен
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)

        expire = datetime.utcnow() + expires_delta

        to_encode = subject.copy()
        to_encode.update({"exp": expire, "type": "access"})

        encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return encoded_jwt

    @staticmethod
    def create_refresh_token(subject: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        """
        Создание refresh токена.

        Args:
            subject: Данные для кодирования в токен
            expires_delta: Время жизни токена (по умолчанию из настроек)

        Returns:
            JWT токен
        """
        if expires_delta is None:
            expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)

        expire = datetime.utcnow() + expires_delta

        to_encode = subject.copy()
        to_encode.update({"exp": expire, "type": "refresh"})

        encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> dict[str, Any] | None:
        """
        Декодирование JWT токена.

        Args:
            token: JWT токен

        Returns:
            Декодированные данные или None при ошибке
        """
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            return payload
        except Exception:
            return None

    @staticmethod
    def verify_token(token: str, token_type: str = "access") -> dict[str, Any] | None:
        """
        Проверка и декодирование токена с проверкой типа.

        Args:
            token: JWT токен
            token_type: Ожидаемый тип токена ("access" или "refresh")

        Returns:
            Декодированные данные или None при ошибке
        """
        payload = JWTHelper.decode_token(token)
        if payload is None:
            return None

        if payload.get("type") != token_type:
            return None

        return payload
