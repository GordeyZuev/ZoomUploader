"""OAuth response schemas."""

from pydantic import BaseModel


class OAuthImplicitFlowResponse(BaseModel):
    """Ответ для Implicit Flow."""

    method: str
    app_id: str
    redirect_uri: str | None = None
