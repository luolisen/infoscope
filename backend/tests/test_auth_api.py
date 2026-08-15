from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.errors import ApiError
from infoscope.schemas.auth import SessionResponse, SessionState, SessionUser
from infoscope.services.auth import get_auth_service


class FakeAuthService:
    def __init__(self) -> None:
        self.logged_out_token: str | None = None

    async def get_session(self, token: str | None) -> SessionResponse:
        if token == "valid-session-token":
            return SessionResponse(
                state=SessionState.ONBOARDING_REQUIRED,
                user=SessionUser(username="alan"),
            )
        return SessionResponse(state=SessionState.ANONYMOUS, user=None)

    async def register(self, username: str, password: str) -> tuple[SessionResponse, str]:
        assert password == "correct-horse"
        return (
            SessionResponse(
                state=SessionState.ONBOARDING_REQUIRED,
                user=SessionUser(username=username),
            ),
            "new-session-token",
        )

    async def login(self, username: str, password: str) -> tuple[SessionResponse, str]:
        raise ApiError(
            status_code=401,
            code="INVALID_CREDENTIALS",
            message="Username or password is invalid.",
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
        "user": {"username": "alan"},
    }


async def test_register_sets_the_server_side_session_cookie() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/register",
                json={"username": "alan", "password": "correct-horse"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json() == {
        "state": "onboarding_required",
        "user": {"username": "alan"},
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("is_session=new-session-token;")
    assert "HttpOnly" in cookie
    assert "Max-Age=2592000" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie


async def test_login_failure_uses_the_stable_error_contract() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"username": "alan", "password": "incorrect-password"},
                headers={"x-request-id": "login-request-id"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "INVALID_CREDENTIALS",
            "message": "Username or password is invalid.",
            "request_id": "login-request-id",
        }
    }


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


async def test_credentials_reject_blank_username_and_short_password() -> None:
    service = FakeAuthService()
    app.dependency_overrides[get_auth_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/register",
                json={"username": "   ", "password": "short"},
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
