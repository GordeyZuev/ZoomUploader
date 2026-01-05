"""Схемы для управления пользователями."""

from .profile import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    UserProfileUpdate,
)

__all__ = [
    "UserProfileUpdate",
    "ChangePasswordRequest",
    "DeleteAccountRequest",
]

