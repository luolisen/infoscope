from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from infoscope.analysis.brief_schemas import (
    BriefBaseAnalysis,
    BriefClaim,
    BriefDecision,
    BriefEventInput,
    BriefInput,
    BriefPayload,
    BriefPersonalization,
    BriefTimelineEntry,
)
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.intelligence_client import DeepSeekIntelligenceClient
from infoscope.analysis.intelligence_schemas import BaseAnalysisEntity
from infoscope.api.app import app
from infoscope.api.dependencies import get_ready_user
from infoscope.models import User
from infoscope.schemas.brief import BriefLatestItem, BriefLatestResponse
from infoscope.services.brief import BriefError, BriefRepository, BriefRunner
from infoscope.services.brief_api import get_brief_api_service


def _event() -> BriefEventInput:
    claim_id = uuid4()
    return BriefEventInput(
        event_id=uuid4(),
        source_personalized_event_id=uuid4(),
        personalization=BriefPersonalization(
            priority="high",
            why_it_matters="This affects Alan's selected scope.",
            personalized_angle="Track the downstream change.",
        ),
        title="A grounded event",
        overview="The persisted overview.",
        state="developing",
        display_time=datetime(2026, 8, 16, 12, tzinfo=UTC),
        updated_at=datetime(2026, 8, 16, 13, tzinfo=UTC),
        base_analysis=BriefBaseAnalysis(
            base_analysis_id=uuid4(),
            summary="The current base analysis.",
            event_type="technology.release",
            importance="high",
            topics=["AI"],
            entities=[BaseAnalysisEntity(name="Example", entity_type="company")],
        ),
        claims=[BriefClaim(claim_id=claim_id, text="A persisted claim.", state="confirmed")],
        timeline=[
            BriefTimelineEntry(
                timeline_entry_id=uuid4(),
                occurred_at=datetime(2026, 8, 16, 11, tzinfo=UTC),
                summary="The claim occurred.",
                claim_ids=[claim_id],
            )
        ],
        conflicts=[],
    )


def _input() -> BriefInput:
    return BriefInput(
        user_id=uuid4(),
        source_personalization_artifact_id=uuid4(),
        events=[_event()],
    )


def _ready_user() -> User:
    return User(
        username="alan",
        username_normalized="alan",
        password_hash="unused",
        onboarding_completed=True,
        scope_ids=["ai"],
        investment_market_ids=[],
        focus_ids=["deep_context"],
    )


def test_output_must_cover_events_in_backend_order() -> None:
    value = _input()
    decision = BriefDecision(
        event_id=value.events[0].event_id,
        summary="A concise grounded summary.",
        rationale="The summary compresses the supplied facts.",
    )
    BriefRepository.validate_output(BriefPayload(items=[decision]), value)

    with pytest.raises(BriefError, match="BRIEF_SCHEMA_INVALID"):
        BriefRepository.validate_output(BriefPayload(items=[]), value)


def test_relation_claim_ids_must_be_scoped_and_backend_ordered() -> None:
    event = _event()
    other = uuid4()
    document = event.model_dump()
    document["timeline"][0]["claim_ids"] = [other]
    with pytest.raises(ValueError, match="out-of-scope Claim"):
        BriefEventInput.model_validate(document)


def test_input_requires_priority_then_time_then_uuid_order() -> None:
    first = _event()
    second = _event().model_copy(
        update={
            "personalization": first.personalization.model_copy(update={"priority": "critical"})
        }
    )
    value = BriefInput(
        user_id=uuid4(),
        source_personalization_artifact_id=uuid4(),
        events=[second, first],
    )
    assert value.events == [second, first]
    with pytest.raises(ValueError, match="Backend selection order"):
        BriefInput(
            user_id=value.user_id,
            source_personalization_artifact_id=value.source_personalization_artifact_id,
            events=[first, second],
        )


@pytest.mark.asyncio
async def test_empty_brief_persists_deterministic_artifact_without_model() -> None:
    value = BriefInput(
        user_id=uuid4(),
        source_personalization_artifact_id=uuid4(),
        events=[],
    )
    run = SimpleNamespace(id=uuid4(), status="pending", attempt_count=0, max_attempts=3)

    class Repository:
        async def input_snapshot(self, _user_id):
            return value

        async def create_or_reuse(self, _value, *, max_attempts):
            assert max_attempts == 3
            return run

        async def start_attempt(self, _run_id):
            run.status = "running"
            return run

        async def persist_success(self, _run_id, original, response):
            assert original == value
            assert response is None
            run.status = "completed"
            return run

    class NoModel:
        async def generate_brief(self, _value):
            raise AssertionError("an empty Brief must not call the model")

    result = await BriefRunner(Repository(), NoModel(), max_attempts=3).run_user(value.user_id)  # type: ignore[arg-type]
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_intelligence_adapter_uses_strict_brief_contract() -> None:
    value = _input()

    async def handler(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)
        prompt = document["messages"][1]["content"]
        assert "brief_input.v1" in prompt
        assert "raw" not in prompt.casefold()
        assert "provenance" not in prompt.casefold()
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "brief.v1",
                                    "items": [
                                        {
                                            "event_id": str(value.events[0].event_id),
                                            "summary": "A concise grounded summary.",
                                            "rationale": "Compressed supplied facts only.",
                                        }
                                    ],
                                }
                            )
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    config = AnalysisConfig("https://api.example.com", "model", ("key",), 10, 0, 1024)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await DeepSeekIntelligenceClient(client=client, config=config).generate_brief(
            value
        )
    assert response.payload.items[0].event_id == value.events[0].event_id


@pytest.mark.asyncio
async def test_latest_api_uses_immutable_snapshot_title_and_public_fields_only() -> None:
    event_id = uuid4()

    class Service:
        async def latest(self, user):
            assert user.username == "alan"
            return BriefLatestResponse(
                generated_at=datetime(2026, 8, 16, 14, tzinfo=UTC),
                items=[
                    BriefLatestItem(
                        event_id=event_id,
                        title="Frozen title",
                        summary="Public summary",
                        why_it_matters="Public personalization",
                    )
                ],
            )

    app.dependency_overrides[get_ready_user] = _ready_user
    app.dependency_overrides[get_brief_api_service] = Service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/brief/latest")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "generated_at": "2026-08-16T14:00:00Z",
        "items": [
            {
                "event_id": str(event_id),
                "title": "Frozen title",
                "summary": "Public summary",
                "why_it_matters": "Public personalization",
            }
        ],
    }
