from typing import Annotated

from fastapi import APIRouter, Depends

from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.health import HealthResponse
from infoscope.services.health import HealthService, get_health_service

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={500: {"model": ErrorResponse}},
)
async def get_health(
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    return await service.check()
