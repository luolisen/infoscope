from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from infoscope.config import Settings, get_settings
from infoscope.schemas.auth import LocalAccessRequest, SessionResponse
from infoscope.schemas.common import ErrorResponse
from infoscope.services.auth import AuthService, get_auth_service

SESSION_COOKIE_NAME = "is_session"

router = APIRouter(tags=["auth"])

SESSION_COOKIE_HEADER = {
    "Set-Cookie": {
        "description": "HttpOnly is_session cookie.",
        "schema": {"type": "string"},
    }
}


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/session", response_model=SessionResponse)
async def get_current_session(
    service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> SessionResponse:
    return await service.get_session(token)


@router.post(
    "/auth/local",
    response_model=SessionResponse,
    responses={
        200: {"headers": SESSION_COOKIE_HEADER},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def local_access(
    request: LocalAccessRequest,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionResponse:
    session, token = await service.local_access(request.display_name)
    set_session_cookie(response, token, settings)
    return session


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ErrorResponse}},
)
async def logout(
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    await service.logout(token)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax")
