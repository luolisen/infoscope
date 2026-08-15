from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.errors import ApiError
from infoscope.models import User
from infoscope.schemas.now import NowResponse, WindowStats
from infoscope.services.now import NowService, get_now_service


def ready_user() -> User:
    return User(
        username="alan",
        username_normalized="alan",
        password_hash="not-used",
        onboarding_completed=True,
        scope_ids=["ai"],
        investment_market_ids=[],
        focus_ids=["deep_context"],
    )


class FixedNowService:
    def get_now(self, *, limit: int, cursor: str | None) -> NowResponse:
        assert limit == 20
        assert cursor is None
        return NowResponse(
            window_stats=WindowStats(
                window_started_at=datetime(2026, 8, 15, 12, tzinfo=UTC),
                window_ended_at=datetime(2026, 8, 15, 13, tzinfo=UTC),
                raw_information_count=0,
                event_count=0,
                relevant_event_count=0,
            ),
            items=[],
            next_cursor=None,
        )


async def test_now_returns_the_frozen_empty_contract() -> None:
    app.dependency_overrides[get_ready_user] = ready_user
    app.dependency_overrides[get_now_service] = FixedNowService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/now")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "window_stats": {
            "window_started_at": "2026-08-15T12:00:00Z",
            "window_ended_at": "2026-08-15T13:00:00Z",
            "raw_information_count": 0,
            "event_count": 0,
            "relevant_event_count": 0,
        },
        "items": [],
        "next_cursor": None,
    }


async def test_now_rejects_a_limit_above_the_frozen_maximum() -> None:
    app.dependency_overrides[get_ready_user] = ready_user
    app.dependency_overrides[get_now_service] = FixedNowService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/now?limit=101")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_now_requires_completed_onboarding() -> None:
    async def onboarding_required() -> User:
        raise ApiError(
            status_code=403,
            code="ONBOARDING_REQUIRED",
            message="Onboarding must be completed before accessing this resource.",
        )

    app.dependency_overrides[get_ready_user] = onboarding_required
    app.dependency_overrides[get_now_service] = FixedNowService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/now")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ONBOARDING_REQUIRED"


async def test_now_requires_authentication() -> None:
    async def auth_required() -> User:
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="A valid session is required.",
        )

    app.dependency_overrides[get_ready_user] = auth_required
    app.dependency_overrides[get_now_service] = FixedNowService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/now")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_empty_now_uses_an_exact_one_hour_utc_window() -> None:
    response = NowService().get_now(limit=20, cursor=None)

    assert response.window_stats.window_started_at.tzinfo is UTC
    assert response.window_stats.window_started_at.minute == 0
    assert response.window_stats.window_started_at.second == 0
    assert response.window_stats.window_started_at.microsecond == 0
    assert (
        response.window_stats.window_ended_at - response.window_stats.window_started_at
        == timedelta(hours=1)
    )
    assert response.items == []
    assert response.next_cursor is None
