import pytest
from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.api.dependencies import get_authenticated_user
from infoscope.errors import ApiError
from infoscope.models import User
from infoscope.schemas.onboarding import (
    FOCUS_OPTIONS,
    INVESTMENT_MARKET_OPTIONS,
    SCOPE_OPTIONS,
    FocusId,
    InvestmentMarketId,
    OnboardingAnswers,
    OnboardingResponse,
    OnboardingSelection,
    ScopeId,
)
from infoscope.services.onboarding import OnboardingService, get_onboarding_service


def response_for(*, completed: bool) -> OnboardingResponse:
    return OnboardingResponse(
        completed=completed,
        scope_options=SCOPE_OPTIONS,
        investment_market_options=INVESTMENT_MARKET_OPTIONS,
        focus_options=FOCUS_OPTIONS,
        answers=OnboardingAnswers(
            scope_ids=[ScopeId.AI, ScopeId.INVESTMENT] if completed else [],
            investment_market_ids=[InvestmentMarketId.US_STOCK] if completed else [],
            focus_ids=[FocusId.TECHNICAL_DETAILS] if completed else [],
        ),
    )


class FakeOnboardingService:
    def __init__(self) -> None:
        self.updated_selection: OnboardingSelection | None = None

    def get_onboarding(self, user: User) -> OnboardingResponse:
        return response_for(completed=user.onboarding_completed)

    async def update_onboarding(
        self, user: User, selection: OnboardingSelection
    ) -> OnboardingResponse:
        self.updated_selection = selection
        user.onboarding_completed = True
        return response_for(completed=True)

    def get_scope(self, user: User) -> OnboardingResponse:
        if not user.onboarding_completed:
            raise ApiError(
                status_code=403,
                code="ONBOARDING_REQUIRED",
                message="Onboarding must be completed before accessing this resource.",
            )
        return response_for(completed=True)

    async def update_scope(
        self, user: User, selection: OnboardingSelection
    ) -> OnboardingResponse:
        self.updated_selection = selection
        return self.get_scope(user)


def pending_user() -> User:
    return User(
        username="alan",
        username_normalized="alan",
        password_hash="not-used",
        onboarding_completed=False,
        scope_ids=[],
        investment_market_ids=[],
        focus_ids=[],
    )


async def test_get_onboarding_returns_the_frozen_options() -> None:
    service = FakeOnboardingService()
    app.dependency_overrides[get_authenticated_user] = pending_user
    app.dependency_overrides[get_onboarding_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/onboarding")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "completed": False,
        "scope_options": [
            {"id": "ai", "label": "AI"},
            {"id": "open_source", "label": "开源社区"},
            {"id": "technology", "label": "技术"},
            {"id": "science", "label": "科学"},
            {"id": "investment", "label": "投资"},
        ],
        "investment_market_options": [
            {"id": "china_market", "label": "中国市场"},
            {"id": "us_stock", "label": "美股"},
            {"id": "crypto_market", "label": "加密市场"},
        ],
        "focus_options": [
            {"id": "technical_details", "label": "技术细节"},
            {"id": "research_progress", "label": "研究进展"},
            {"id": "major_changes", "label": "重要变化"},
            {"id": "breaking_events", "label": "突发事件"},
            {"id": "niche_trends", "label": "小众趋势"},
            {"id": "industry_changes", "label": "行业变化"},
            {"id": "controversy_changes", "label": "争议变化"},
            {"id": "deep_context", "label": "深度背景"},
        ],
        "answers": {
            "scope_ids": [],
            "investment_market_ids": [],
            "focus_ids": [],
        },
    }


async def test_put_onboarding_completes_the_frozen_selection() -> None:
    service = FakeOnboardingService()
    app.dependency_overrides[get_authenticated_user] = pending_user
    app.dependency_overrides[get_onboarding_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/onboarding",
                json={
                    "scope_ids": ["ai", "investment"],
                    "investment_market_ids": ["us_stock"],
                    "focus_ids": ["technical_details"],
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["completed"] is True
    assert service.updated_selection is not None
    assert service.updated_selection.scope_ids == [ScopeId.AI, ScopeId.INVESTMENT]


async def test_invalid_onboarding_combination_uses_the_frozen_error_code() -> None:
    service = FakeOnboardingService()
    app.dependency_overrides[get_authenticated_user] = pending_user
    app.dependency_overrides[get_onboarding_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/onboarding",
                json={
                    "scope_ids": ["ai"],
                    "investment_market_ids": ["us_stock"],
                    "focus_ids": ["technical_details"],
                },
                headers={"x-request-id": "invalid-selection-id"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "INVALID_ONBOARDING_SELECTION",
            "message": "The onboarding selection is invalid.",
            "request_id": "invalid-selection-id",
        }
    }


@pytest.mark.parametrize(
    "selection",
    [
        {
            "scope_ids": [],
            "investment_market_ids": [],
            "focus_ids": ["technical_details"],
        },
        {
            "scope_ids": ["ai", "ai"],
            "investment_market_ids": [],
            "focus_ids": ["technical_details"],
        },
        {
            "scope_ids": ["investment"],
            "investment_market_ids": [],
            "focus_ids": ["technical_details"],
        },
        {
            "scope_ids": ["ai"],
            "investment_market_ids": [],
            "focus_ids": [],
        },
        {
            "scope_ids": ["not_frozen"],
            "investment_market_ids": [],
            "focus_ids": ["technical_details"],
        },
    ],
)
async def test_all_invalid_selection_shapes_use_the_frozen_error_code(
    selection: dict[str, list[str]],
) -> None:
    service = FakeOnboardingService()
    app.dependency_overrides[get_authenticated_user] = pending_user
    app.dependency_overrides[get_onboarding_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put("/api/v1/onboarding", json=selection)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_ONBOARDING_SELECTION"


async def test_scope_requires_completed_onboarding() -> None:
    service = FakeOnboardingService()
    app.dependency_overrides[get_authenticated_user] = pending_user
    app.dependency_overrides[get_onboarding_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/scope")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ONBOARDING_REQUIRED"


async def test_onboarding_requires_authentication() -> None:
    async def auth_required() -> User:
        raise ApiError(
            status_code=401,
            code="AUTH_REQUIRED",
            message="A valid session is required.",
        )

    app.dependency_overrides[get_authenticated_user] = auth_required
    app.dependency_overrides[get_onboarding_service] = FakeOnboardingService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/onboarding")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


async def test_service_persists_scope_and_requests_personalization_refresh() -> None:
    class FakeDatabase:
        committed = False

        async def commit(self) -> None:
            self.committed = True

    database = FakeDatabase()
    service = OnboardingService(database)  # type: ignore[arg-type]
    user = pending_user()
    selection = OnboardingSelection(
        scope_ids=[ScopeId.OPEN_SOURCE],
        investment_market_ids=[],
        focus_ids=[FocusId.DEEP_CONTEXT],
    )

    response = await service.update_onboarding(user, selection)

    assert database.committed is True
    assert user.scope_ids == ["open_source"]
    assert user.investment_market_ids == []
    assert user.focus_ids == ["deep_context"]
    assert user.personalization_update_requested_at is not None
    assert response.completed is True
