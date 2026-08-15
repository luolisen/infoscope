from typing import Annotated

from fastapi import APIRouter, Depends

from infoscope.api.dependencies import get_authenticated_user
from infoscope.models import User
from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.onboarding import OnboardingResponse, OnboardingSelection
from infoscope.services.onboarding import OnboardingService, get_onboarding_service

router = APIRouter(tags=["onboarding"])

ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.get(
    "/onboarding",
    response_model=OnboardingResponse,
    responses={401: {"model": ErrorResponse}},
)
async def get_onboarding(
    user: Annotated[User, Depends(get_authenticated_user)],
    service: Annotated[OnboardingService, Depends(get_onboarding_service)],
) -> OnboardingResponse:
    return service.get_onboarding(user)


@router.put(
    "/onboarding",
    response_model=OnboardingResponse,
    responses=ERROR_RESPONSES,
)
async def update_onboarding(
    selection: OnboardingSelection,
    user: Annotated[User, Depends(get_authenticated_user)],
    service: Annotated[OnboardingService, Depends(get_onboarding_service)],
) -> OnboardingResponse:
    return await service.update_onboarding(user, selection)


@router.get(
    "/scope",
    response_model=OnboardingResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def get_scope(
    user: Annotated[User, Depends(get_authenticated_user)],
    service: Annotated[OnboardingService, Depends(get_onboarding_service)],
) -> OnboardingResponse:
    return service.get_scope(user)


@router.put(
    "/scope",
    response_model=OnboardingResponse,
    responses=ERROR_RESPONSES,
)
async def update_scope(
    selection: OnboardingSelection,
    user: Annotated[User, Depends(get_authenticated_user)],
    service: Annotated[OnboardingService, Depends(get_onboarding_service)],
) -> OnboardingResponse:
    return await service.update_scope(user, selection)
