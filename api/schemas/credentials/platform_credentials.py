"""Pydantic schemas for platform credentials validation."""

from pydantic import BaseModel, Field, field_validator


class YouTubeClientSecretsWeb(BaseModel):
    """YouTube client secrets (web format)."""

    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    project_id: str | None = Field(None, description="Google Cloud project ID")
    auth_uri: str = Field(
        default="https://accounts.google.com/o/oauth2/auth", description="Authorization URI"
    )
    token_uri: str = Field(default="https://oauth2.googleapis.com/token", description="Token URI")
    auth_provider_x509_cert_url: str | None = Field(None, description="Auth provider cert URL")
    redirect_uris: list[str] | None = Field(None, description="Redirect URIs")


class YouTubeClientSecretsInstalled(BaseModel):
    """YouTube client secrets (installed format)."""

    client_id: str = Field(..., description="Google OAuth client ID")
    client_secret: str = Field(..., description="Google OAuth client secret")
    project_id: str | None = Field(None, description="Google Cloud project ID")
    auth_uri: str = Field(
        default="https://accounts.google.com/o/oauth2/auth", description="Authorization URI"
    )
    token_uri: str = Field(default="https://oauth2.googleapis.com/token", description="Token URI")
    auth_provider_x509_cert_url: str | None = Field(None, description="Auth provider cert URL")
    redirect_uris: list[str] | None = Field(None, description="Redirect URIs")


class YouTubeToken(BaseModel):
    """YouTube access token data."""

    token: str = Field(..., description="Access token")
    refresh_token: str | None = Field(None, description="Refresh token")
    token_uri: str = Field(default="https://oauth2.googleapis.com/token", description="Token URI")
    client_id: str = Field(..., description="Client ID")
    client_secret: str = Field(..., description="Client secret")
    scopes: list[str] = Field(..., description="OAuth scopes")
    expiry: str | None = Field(None, description="Token expiry (ISO format)")


class YouTubeCredentialsManual(BaseModel):
    """
    YouTube credentials for manual input via API.

    Supports both formats:
    1. Complete bundle with client_secrets and token
    2. Simple format with just token data
    """

    client_secrets: dict | None = Field(
        None, description="Client secrets (can contain 'web' or 'installed' key)"
    )
    token: YouTubeToken | None = Field(None, description="Token data")

    @field_validator("client_secrets")
    @classmethod
    def validate_client_secrets(cls, v):
        """Validate client secrets structure."""
        if v is None:
            return v

        # Check if it has 'web' or 'installed' key
        if "web" in v:
            YouTubeClientSecretsWeb(**v["web"])
        elif "installed" in v:
            YouTubeClientSecretsInstalled(**v["installed"])
        else:
            # Try to parse directly
            try:
                YouTubeClientSecretsWeb(**v)
            except Exception:
                try:
                    YouTubeClientSecretsInstalled(**v)
                except Exception as e:
                    raise ValueError(f"Invalid client_secrets format: {e}") from e

        return v

    @field_validator("token")
    @classmethod
    def validate_token(cls, v, info):
        """Validate token if client_secrets is provided."""
        if v is None and info.data.get("client_secrets") is None:
            raise ValueError("Either client_secrets or token must be provided")
        return v


class VKCredentialsManual(BaseModel):
    """VK credentials for manual input via API (VK ID format)."""

    client_id: str | None = Field(None, description="VK application ID")
    client_secret: str | None = Field(None, description="VK client secret")
    access_token: str = Field(..., description="VK access token", min_length=10)
    refresh_token: str | None = Field(None, description="VK ID refresh token")
    user_id: int | None = Field(None, description="VK user ID")
    expires_in: int | None = Field(None, description="Token expiry in seconds")
    expiry: str | None = Field(None, description="Token expiry (ISO format)")

    # Legacy fields (optional)
    group_id: str | None = Field(None, description="VK group ID for posting")
    album_id: str | None = Field(None, description="VK album ID")
    app_id: str | None = Field(None, description="VK app ID (legacy)")
    scope: str | None = Field(None, description="VK scopes (legacy)")


class ZoomCredentialsManual(BaseModel):
    """
    Zoom credentials for manual input via API.

    Supports two formats:
    1. Server-to-Server OAuth (account_id + client_id + client_secret)
    2. OAuth 2.0 with tokens (access_token + refresh_token)
    """

    # Server-to-Server OAuth fields
    account_id: str | None = Field(None, description="Zoom account ID (Server-to-Server)", min_length=5)
    client_id: str | None = Field(None, description="Zoom client ID", min_length=5)
    client_secret: str | None = Field(None, description="Zoom client secret", min_length=10)
    account: str | None = Field(None, description="Account name for identification")

    # OAuth 2.0 fields
    access_token: str | None = Field(None, description="Zoom OAuth access token", min_length=10)
    refresh_token: str | None = Field(None, description="Zoom OAuth refresh token")
    token_type: str | None = Field(None, description="Token type (usually 'bearer')")
    scope: str | None = Field(None, description="OAuth scopes granted")
    expires_in: int | None = Field(None, description="Token expiry in seconds")
    expiry: str | None = Field(None, description="Token expiry (ISO format)")

    @field_validator("account_id", "client_id", "client_secret")
    @classmethod
    def validate_not_empty(cls, v, info):
        """Ensure fields are not empty strings if provided."""
        if v and not v.strip():
            raise ValueError(f"{info.field_name} cannot be empty")
        return v.strip() if v else None

    def model_post_init(self, __context):
        """Validate that either Server-to-Server or OAuth format is provided."""
        has_server_to_server = bool(self.account_id and self.client_id and self.client_secret)
        has_oauth = bool(self.access_token)

        if not has_server_to_server and not has_oauth:
            raise ValueError(
                "Either Server-to-Server credentials (account_id, client_id, client_secret) "
                "or OAuth credentials (access_token) must be provided"
            )

