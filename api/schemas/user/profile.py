"""Схемы для управления профилем пользователя."""

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserProfileUpdate(BaseModel):
    """Схема для обновления профиля пользователя.

    Пользователь может обновить только свое имя и email.
    Остальные поля (permissions, role) могут менять только админы.
    """

    full_name: str | None = Field(None, max_length=255, description="Полное имя пользователя")
    email: EmailStr | None = Field(None, description="Email пользователя")

    class Config:
        json_schema_extra = {
            "example": {
                "full_name": "Иван Петров",
                "email": "ivan.petrov@example.com",
            }
        }


class ChangePasswordRequest(BaseModel):
    """Схема для смены пароля."""

    current_password: str = Field(..., min_length=1, description="Текущий пароль")
    new_password: str = Field(..., min_length=8, max_length=100, description="Новый пароль")

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Валидация нового пароля."""
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        if not any(char.isdigit() for char in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(char.isupper() for char in v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "current_password": "OldPassword123",
                "new_password": "NewSecurePassword123",
            }
        }


class DeleteAccountRequest(BaseModel):
    """Схема для подтверждения удаления аккаунта."""

    password: str = Field(..., description="Пароль для подтверждения")
    confirmation: str = Field(
        ...,
        description="Пользователь должен ввести 'DELETE' для подтверждения",
    )

    @field_validator("confirmation")
    @classmethod
    def validate_confirmation(cls, v: str) -> str:
        """Проверка, что пользователь действительно хочет удалить аккаунт."""
        if v != "DELETE":
            raise ValueError("Для подтверждения удаления введите 'DELETE'")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "password": "MyPassword123",
                "confirmation": "DELETE",
            }
        }

