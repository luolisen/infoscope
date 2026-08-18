from typing import Annotated

from fastapi import APIRouter, Depends

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.research_capability import ResearchCapabilityResponse
from infoscope.services.research_capability import (
    ResearchCapabilityService,
    get_research_capability_service,
)

router = APIRouter(tags=["research"])


@router.get(
    "/research/capability",
    response_model=ResearchCapabilityResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def research_capability(
    _user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[ResearchCapabilityService, Depends(get_research_capability_service)],
) -> ResearchCapabilityResponse:
    return await service.status()
