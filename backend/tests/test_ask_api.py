from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.ask import (
    AskAcceptedResponse,
    AskCompletedResponse,
    AskFailedResponse,
    AskResult,
)
from infoscope.schemas.common import ErrorDetail
from infoscope.services.ask_api import get_ask_service


def _user() -> User:
    return User(
        id=uuid4(),
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
    )


class _Service:
    def __init__(self) -> None:
        self.ask_id = uuid4()

    async def create(self, user, value):
        assert value.question == "What changed?"
        return AskAcceptedResponse(ask_id=self.ask_id)

    async def get(self, user, ask_id, request_id):
        assert ask_id == self.ask_id
        return AskCompletedResponse(
            ask_id=ask_id,
            status="completed",
            result=AskResult(
                answer="Grounded answer",
                event_ids=[uuid4()],
                claim_ids=[],
                timeline_ids=[],
                conflict_ids=[],
                evidence_ids=[],
                updated_event_ids=[],
            ),
        )


async def test_ask_post_is_accepted_and_get_returns_strict_completed_dto() -> None:
    service = _Service()
    app.dependency_overrides[get_ready_user] = _user
    app.dependency_overrides[get_ask_service] = lambda: service
    event_id = uuid4()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            accepted = await client.post(
                "/api/v1/ask",
                json={"event_ids": [str(event_id)], "question": "  What changed?  "},
            )
            completed = await client.get(f"/api/v1/ask/{service.ask_id}")
    finally:
        app.dependency_overrides.clear()

    assert accepted.status_code == 202
    assert accepted.json() == {"ask_id": str(service.ask_id), "status": "pending"}
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["result"]["answer"] == "Grounded answer"
    assert completed.json()["error"] is None


def test_failed_public_dto_contains_only_generic_error() -> None:
    ask_id = uuid4()
    response = AskFailedResponse(
        ask_id=ask_id,
        status="failed",
        error=ErrorDetail(
            code="ASK_FAILED",
            message="Ask processing failed.",
            request_id="poll-request-id",
        ),
    )
    assert response.model_dump(mode="json") == {
        "ask_id": str(ask_id),
        "status": "failed",
        "result": None,
        "error": {
            "code": "ASK_FAILED",
            "message": "Ask processing failed.",
            "request_id": "poll-request-id",
        },
    }
