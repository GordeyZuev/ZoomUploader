"""Health check endpoints."""

from fastapi import APIRouter

from api.schemas.common.health import HealthCheckResponse

router = APIRouter(tags=["Health"])


@router.get("/api/v1/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint."""
    return HealthCheckResponse(
        status="ok",
        service="LEAP API - Lecture Enhancement & Automation Platform",
    )
