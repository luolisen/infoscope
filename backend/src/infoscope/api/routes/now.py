from typing import Annotated

from fastapi import APIRouter, Depends, Query

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.now import NowResponse
from infoscope.services.now import NowService, get_now_service

router = APIRouter(tags=["now"])


@router.get(
    "/now",
    response_model=NowResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_now(
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[NowService, Depends(get_now_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> NowResponse:
    return await service.get_now(user, limit=limit, cursor=cursor)
