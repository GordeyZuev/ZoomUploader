"""Response schemas for credentials endpoints."""

from pydantic import BaseModel, Field


class CredentialResponse(BaseModel):
    """Ответ с информацией об учетных данных."""

    id: int = Field(..., description="ID учетных данных")
    platform: str = Field(..., description="Платформа")
    account_name: str | None = Field(None, description="Имя аккаунта")
    is_active: bool = Field(..., description="Активны ли учетные данные")
    last_used_at: str | None = Field(None, description="Время последнего использования")
    credentials: dict | None = Field(None, description="Учетные данные (только при запросе с флагом include_data)")


class CredentialStatusResponse(BaseModel):
    """Статус credentials пользователя."""

    user_id: int
    available_platforms: list[str]
    credentials_status: dict[str, bool]


class CredentialDeleteResponse(BaseModel):
    """Подтверждение удаления."""

    message: str
