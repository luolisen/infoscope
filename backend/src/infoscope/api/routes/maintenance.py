from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.common import ErrorResponse
from infoscope.schemas.maintenance import (
    MaintenanceAcceptedResponse,
    MaintenanceRunResponse,
    MaintenanceStatusResponse,
)
from infoscope.services.maintenance import MaintenanceService, get_maintenance_service

router = APIRouter(tags=["maintenance"])


@router.get(
    "/maintenance/status",
    response_model=MaintenanceStatusResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def maintenance_status(
    _user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[MaintenanceService, Depends(get_maintenance_service)],
) -> MaintenanceStatusResponse:
    return await service.status()


@router.post(
    "/maintenance/runs",
    response_model=MaintenanceAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def create_maintenance_run(
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[MaintenanceService, Depends(get_maintenance_service)],
) -> MaintenanceAcceptedResponse:
    return await service.create(user)


@router.get(
    "/maintenance/runs/{run_id}",
    response_model=MaintenanceRunResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_maintenance_run(
    run_id: UUID,
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[MaintenanceService, Depends(get_maintenance_service)],
) -> MaintenanceRunResponse:
    return await service.get(user, run_id)
