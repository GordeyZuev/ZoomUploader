"""Authentication schemas"""

from .credential import (
    UserCredentialBase,
    UserCredentialCreate,
    UserCredentialInDB,
    UserCredentialResponse,
    UserCredentialUpdate,
)
from .operations import LogoutAllResponse, LogoutResponse
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
    "ChangePasswordRequest",
    "LoginRequest",
    "LogoutAllResponse",
    # Operations
    "LogoutResponse",
    "QuotaStatusResponse",
    # Quota Usage
    "QuotaUsageCreate",
    "QuotaUsageInDB",
    "QuotaUsageResponse",
    "QuotaUsageUpdate",
    # Token
    "RefreshTokenBase",
    "RefreshTokenCreate",
    "RefreshTokenInDB",
    "RefreshTokenRequest",
    # Requests
    "RegisterRequest",
    # Subscription Plans
    "SubscriptionPlanCreate",
    "SubscriptionPlanInDB",
    "SubscriptionPlanResponse",
    "SubscriptionPlanUpdate",
    "TokenPair",
    # Responses
    "TokenResponse",
    # User
    "UserBase",
    "UserCreate",
    # Credential
    "UserCredentialBase",
    "UserCredentialCreate",
    "UserCredentialInDB",
    "UserCredentialResponse",
    "UserCredentialUpdate",
    "UserInDB",
    "UserMeResponse",
    "UserResponse",
    # User Subscriptions
    "UserSubscriptionCreate",
    "UserSubscriptionInDB",
    "UserSubscriptionResponse",
    "UserSubscriptionUpdate",
    "UserUpdate",
]
