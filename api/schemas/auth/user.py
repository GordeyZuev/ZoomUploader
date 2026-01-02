"""Pydantic схемы для пользователей."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserBase(BaseModel):
    """Базовая схема пользователя."""

    email: EmailStr = Field(..., description="Email пользователя")
    full_name: str | None = Field(None, max_length=255, description="Полное имя")


class UserCreate(UserBase):
    """Схема для создания пользователя."""

    password: str = Field(..., min_length=8, max_length=100, description="Пароль")

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


class UserUpdate(BaseModel):
    """Схема для обновления пользователя."""

    email: EmailStr | None = None
    full_name: str | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    is_superuser: bool | None = None
    role: str | None = None
    can_transcribe: bool | None = None
    can_process_video: bool | None = None
    can_upload_to_youtube: bool | None = None
    can_upload_to_google_drive: bool | None = None
    last_login_at: datetime | None = None


class UserInDB(UserBase):
    """Схема пользователя в БД."""

    id: int
    hashed_password: str
    is_active: bool = True
    is_verified: bool = False
    is_superuser: bool = False
    role: str = "user"
    can_transcribe: bool = True
    can_process_video: bool = True
    can_upload_to_youtube: bool = True
    can_upload_to_google_drive: bool = True
    created_at: datetime
    last_login_at: datetime | None = None

    class Config:
        from_attributes = True


class UserResponse(BaseModel):
    """Схема ответа с пользователем."""

    id: int
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_verified: bool
    is_superuser: bool
    role: str
    can_transcribe: bool
    can_process_video: bool
    can_upload_to_youtube: bool
    can_upload_to_google_drive: bool
    created_at: datetime
    last_login_at: datetime | None

    class Config:
        from_attributes = True

