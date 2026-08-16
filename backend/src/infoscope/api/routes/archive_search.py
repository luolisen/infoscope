from typing import Annotated

from fastapi import APIRouter, Depends, Query

from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.archive_search import ArchiveResponse, EventSearchResponse
from infoscope.schemas.common import ErrorResponse
from infoscope.services.archive_search import (
    ArchiveSearchService,
    get_archive_search_service,
)

router = APIRouter(tags=["archive", "search"])


@router.get(
    "/archive",
    response_model=ArchiveResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_archive(
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[ArchiveSearchService, Depends(get_archive_search_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> ArchiveResponse:
    return await service.archive(user, limit=limit, cursor=cursor)


@router.get(
    "/search/events",
    response_model=EventSearchResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def search_events(
    user: Annotated[User, Depends(get_ready_user)],
    service: Annotated[ArchiveSearchService, Depends(get_archive_search_service)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> EventSearchResponse:
    return await service.search(
        user,
        query_text=q,
        limit=limit,
        cursor=cursor,
    )
