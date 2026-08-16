from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.ask import AskAcceptedResponse, AskCreateRequest, AskStatusResponse
from infoscope.schemas.common import ErrorResponse
from infoscope.services.ask_api import AskService, get_ask_service

router = APIRouter(tags=["ask"])


@router.post(
    "/ask",
    response_model=AskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_ask(
    value: AskCreateRequest,
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[AskService, Depends(get_ask_service)],
) -> AskAcceptedResponse:
    return await service.create(user, value)


@router.get(
    "/ask/{ask_id}",
    response_model=AskStatusResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_ask(
    ask_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[AskService, Depends(get_ask_service)],
) -> AskStatusResponse:
    current_request_id = getattr(request.state, "request_id", "unknown-request-id")
    return await service.get(user, ask_id, current_request_id)
