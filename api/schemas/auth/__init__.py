"""Схемы для аутентификации."""

from .credential import (
    UserCredentialBase,
    UserCredentialCreate,
    UserCredentialInDB,
    UserCredentialResponse,
    UserCredentialUpdate,
)
from .quota import (
    UserQuotaBase,
    UserQuotaCreate,
    UserQuotaInDB,
    UserQuotaResponse,
    UserQuotaUpdate,
)
from .request import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
)
from .response import MeResponse, TokenResponse
from .token import RefreshTokenBase, RefreshTokenCreate, RefreshTokenInDB, TokenPair
from .user import UserBase, UserCreate, UserInDB, UserResponse, UserUpdate

__all__ = [
    # User
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserInDB",
    "UserResponse",
    # Quota
    "UserQuotaBase",
    "UserQuotaCreate",
    "UserQuotaUpdate",
    "UserQuotaInDB",
    "UserQuotaResponse",
    # Token
    "RefreshTokenBase",
    "RefreshTokenCreate",
    "RefreshTokenInDB",
    "TokenPair",
    # Credential
    "UserCredentialBase",
    "UserCredentialCreate",
    "UserCredentialUpdate",
    "UserCredentialInDB",
    "UserCredentialResponse",
    # Requests
    "RegisterRequest",
    "LoginRequest",
    "RefreshTokenRequest",
    "ChangePasswordRequest",
    # Responses
    "TokenResponse",
    "MeResponse",
]
