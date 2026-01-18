"""OAuth response schemas."""

from pydantic import BaseModel, Field


class OAuthImplicitFlowResponse(BaseModel):
    """Response for OAuth Implicit Flow authorization."""

    method: str = Field(..., description="OAuth method type (e.g., 'implicit_flow')")
    app_id: str = Field(..., description="OAuth application ID")
    redirect_uri: str | None = Field(
        None,
        description="Full authorization URL to redirect user to (includes all query params)",
    )
    scope: str | None = Field(
        None,
        description="Requested permissions (e.g., 'video,groups,wall')",
    )
    response_type: str | None = Field(
        None,
        description="OAuth response type (e.g., 'token' for implicit flow)",
    )
    blank_redirect_uri: str | None = Field(
        None,
        description="Final redirect URI where token will appear in URL hash fragment (e.g., 'https://oauth.vk.com/blank.html')",
    )
