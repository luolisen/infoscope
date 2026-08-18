import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from infoscope.api.app import app
from infoscope.config import Settings
from infoscope.db import close_database, session_factory
from infoscope.errors import ApiError
from infoscope.models import User
from infoscope.schemas.auth import SessionResponse, SessionState, SessionUser
from infoscope.services.auth import AuthService, get_auth_service


class FakeAuthService:
    def __init__(self) -> None:
        self.logged_out_token: str | None = None

    async def get_session(self, token: str | None) -> SessionResponse:
        if token == "valid-session-token":
            return SessionResponse(
                state=SessionState.ONBOARDING_REQUIRED,
                user=SessionUser(display_name="Alan"),
            )
        return SessionResponse(state=SessionState.ANONYMOUS, user=None)

    async def local_access(self, display_name: str) -> tuple[SessionResponse, str]:
        return (
            SessionResponse(
                state=SessionState.ONBOARDING_REQUIRED,
                user=SessionUser(display_name=display_name),
            ),
            "local-session-token",
        )

    async def logout(self, token: str | None) -> None:
        if token is None:
            raise ApiError(
                status_code=401,
                code="AUTH_REQUIRED",
                message="A valid session is required.",
            )
        self.logged_out_token = token


async def test_session_contract_for_anonymous_and_authenticated_users() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            anonymous = await client.get("/api/v1/session")
            client.cookies.set("is_session", "valid-session-token")
            authenticated = await client.get("/api/v1/session")
    finally:
        app.dependency_overrides.clear()

    assert anonymous.status_code == 200
    assert anonymous.json() == {"state": "anonymous", "user": None}
    assert authenticated.status_code == 200
    assert authenticated.json() == {
        "state": "onboarding_required",
        "user": {"display_name": "Alan"},
    }


async def test_local_access_only_requires_a_display_name() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/local",
                json={"display_name": "  Alan  "},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "state": "onboarding_required",
        "user": {"display_name": "Alan"},
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("is_session=local-session-token;")
    assert "HttpOnly" in cookie


async def test_logout_invalidates_and_clears_the_cookie() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            client.cookies.set("is_session", "valid-session-token")
            response = await client.post("/api/v1/auth/logout")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert response.content == b""
    assert service.logged_out_token == "valid-session-token"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith('is_session="";')
    assert "Max-Age=0" in cookie


async def test_local_access_rejects_a_blank_display_name() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/local",
                json={"display_name": "   "},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_logout_requires_a_valid_session() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/auth/logout")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


@pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)
async def test_local_access_reuses_profile_and_only_updates_display_name() -> None:
    internal_username = f"local_{uuid4().hex}"
    settings = Settings(_env_file=None, local_user_username=internal_username)

    try:
        async with session_factory() as database:
            service = AuthService(database, settings)
            first, _ = await service.local_access("第一次称呼")
            assert first.state == SessionState.ONBOARDING_REQUIRED

            user = await database.scalar(
                select(User).where(User.username_normalized == internal_username.casefold())
            )
            assert user is not None
            user.onboarding_completed = True
            user.scope_ids = ["ai", "science"]
            user.investment_market_ids = []
            user.focus_ids = ["major_changes"]
            await database.commit()

            second, _ = await service.local_access("第二次称呼")
            await database.refresh(user)

            assert second.state == SessionState.READY
            assert second.user == SessionUser(display_name="第二次称呼")
            assert user.scope_ids == ["ai", "science"]
            assert user.focus_ids == ["major_changes"]
            assert user.onboarding_completed is True
    finally:
        async with session_factory() as database:
            await database.execute(
                delete(User).where(User.username_normalized == internal_username.casefold())
            )
            await database.commit()
        await close_database()
