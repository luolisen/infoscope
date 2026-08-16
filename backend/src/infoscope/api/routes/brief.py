from typing import Annotated

from fastapi import APIRouter, Depends

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.brief import BriefLatestResponse
from infoscope.schemas.common import ErrorResponse
from infoscope.services.brief_api import BriefApiService, get_brief_api_service

router = APIRouter(tags=["brief"])


@router.get(
    "/brief/latest",
    response_model=BriefLatestResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def latest_brief(
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[BriefApiService, Depends(get_brief_api_service)],
) -> BriefLatestResponse:
    return await service.latest(user)
