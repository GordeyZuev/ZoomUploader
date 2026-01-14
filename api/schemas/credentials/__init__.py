"""Credential schemas for validation."""

from .platform_credentials import (
    VKCredentialsManual,
    YouTubeCredentialsManual,
    ZoomCredentialsManual,
)
from .request import CredentialCreateRequest, CredentialUpdateRequest
from .response import CredentialDeleteResponse, CredentialResponse, CredentialStatusResponse

__all__ = [
    "YouTubeCredentialsManual",
    "VKCredentialsManual",
    "ZoomCredentialsManual",
    "CredentialCreateRequest",
    "CredentialUpdateRequest",
    "CredentialResponse",
    "CredentialStatusResponse",
    "CredentialDeleteResponse",
]
