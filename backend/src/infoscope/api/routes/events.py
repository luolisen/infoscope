from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.event_detail import EventDetailResponse
from infoscope.services.event_detail import EventDetailService, get_event_detail_service

router = APIRouter(tags=["events"])


@router.get(
    "/events/{event_id}",
    response_model=EventDetailResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def get_event_detail(
    event_id: UUID,
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[EventDetailService, Depends(get_event_detail_service)],
) -> EventDetailResponse:
    return await service.get(user, event_id)
