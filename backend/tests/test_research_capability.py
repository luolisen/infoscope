from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.research_capability import ResearchCapabilityResponse
from infoscope.services.research_capability import get_research_capability_service


class CapabilityService:
    def __init__(self, status: str) -> None:
        self.response = ResearchCapabilityResponse(status=status)  # type: ignore[arg-type]

    async def status(self) -> ResearchCapabilityResponse:
        return self.response


def ready_user() -> User:
    return User(
        id=uuid4(),
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
    )


async def test_research_capability_public_contract_is_stable_and_minimal() -> None:
    app.dependency_overrides[get_ready_user] = ready_user
    app.dependency_overrides[get_research_capability_service] = lambda: CapabilityService(
        "unavailable"
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/research/capability")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "unavailable"}
    assert "path" not in response.text.casefold()
    assert "error" not in response.text.casefold()
