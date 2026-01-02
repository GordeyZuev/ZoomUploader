"""Схемы запросов для аутентификации."""

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Запрос на регистрацию."""

    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(..., min_length=8, max_length=100, description="Пароль")
    full_name: str | None = Field(None, max_length=255, description="Полное имя")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Валидация пароля."""
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        if not any(char.isdigit() for char in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(char.isupper() for char in v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        return v


class LoginRequest(BaseModel):
    """Запрос на вход."""

    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(..., description="Пароль")


class RefreshTokenRequest(BaseModel):
    """Запрос на обновление токена."""

    refresh_token: str = Field(..., description="Refresh токен")


class ChangePasswordRequest(BaseModel):
    """Запрос на изменение пароля."""

    old_password: str = Field(..., description="Старый пароль")
    new_password: str = Field(..., min_length=8, max_length=100, description="Новый пароль")

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Валидация пароля."""
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        if not any(char.isdigit() for char in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(char.isupper() for char in v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        return v
