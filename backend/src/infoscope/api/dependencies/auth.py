from typing import Annotated

from fastapi import Cookie, Depends

from infoscope.api.routes.auth import SESSION_COOKIE_NAME
from infoscope.errors import ApiError
from infoscope.models import User
from infoscope.services.auth import AuthService, get_auth_service


async def get_authenticated_user(
    service: Annotated[AuthService, Depends(get_auth_service)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    return await service.require_user(token)


async def get_ready_user(
    user: Annotated[User, Depends(get_authenticated_user)],
) -> User:
    if not user.onboarding_completed:
        raise ApiError(
            status_code=403,
            code="ONBOARDING_REQUIRED",
            message="Onboarding must be completed before accessing this resource.",
        )
    return user
