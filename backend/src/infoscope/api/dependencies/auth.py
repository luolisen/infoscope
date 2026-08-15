from typing import Annotated

from fastapi import Cookie, Depends

from infoscope.api.routes.auth import SESSION_COOKIE_NAME
from infoscope.models import User
from infoscope.services.auth import AuthService, get_auth_service


async def get_authenticated_user(
    service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    return await service.require_user(token)
