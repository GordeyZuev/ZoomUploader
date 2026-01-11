"""Схемы для аутентификации."""

from .credential import (
    UserCredentialBase,
    UserCredentialCreate,
    UserCredentialInDB,
    UserCredentialResponse,
    UserCredentialUpdate,
)
from .request import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
)
from .response import TokenResponse, UserMeResponse
from .subscription import (
    QuotaStatusResponse,
    QuotaUsageCreate,
    QuotaUsageInDB,
    QuotaUsageResponse,
    QuotaUsageUpdate,
    SubscriptionPlanCreate,
    SubscriptionPlanInDB,
    SubscriptionPlanResponse,
    SubscriptionPlanUpdate,
    UserSubscriptionCreate,
    UserSubscriptionInDB,
    UserSubscriptionResponse,
    UserSubscriptionUpdate,
)
from .token import RefreshTokenBase, RefreshTokenCreate, RefreshTokenInDB, TokenPair
from .user import UserBase, UserCreate, UserInDB, UserResponse, UserUpdate

__all__ = [
    # User
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserInDB",
    "UserResponse",
    # Subscription Plans
    "SubscriptionPlanCreate",
    "SubscriptionPlanUpdate",
    "SubscriptionPlanInDB",
    "SubscriptionPlanResponse",
    # User Subscriptions
    "UserSubscriptionCreate",
    "UserSubscriptionUpdate",
    "UserSubscriptionInDB",
    "UserSubscriptionResponse",
    # Quota Usage
    "QuotaUsageCreate",
    "QuotaUsageUpdate",
    "QuotaUsageInDB",
    "QuotaUsageResponse",
    "QuotaStatusResponse",
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
    "UserMeResponse",
]
