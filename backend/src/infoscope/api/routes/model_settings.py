from typing import Annotated

from fastapi import APIRouter, Depends

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.model_settings import ModelSelection, ModelSettingsResponse
from infoscope.services.model_settings import ModelSettingsService, get_model_settings_service

router = APIRouter(tags=["settings"])


@router.get(
    "/settings/models",
    response_model=ModelSettingsResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def get_model_settings(
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[ModelSettingsService, Depends(get_model_settings_service)],
) -> ModelSettingsResponse:
    return await service.get(user.id)


@router.put(
    "/settings/models",
    response_model=ModelSettingsResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def update_model_settings(
    selection: ModelSelection,
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[ModelSettingsService, Depends(get_model_settings_service)],
) -> ModelSettingsResponse:
    return await service.update(user.id, selection)
