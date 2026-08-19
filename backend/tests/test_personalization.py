from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.intelligence_client import DeepSeekIntelligenceClient
from infoscope.analysis.intelligence_schemas import BaseAnalysisEntity
from infoscope.analysis.personalization_schemas import (
    PersonalizationBaseAnalysis,
    PersonalizationDecision,
    PersonalizationEventInput,
    PersonalizationInput,
    PersonalizationPayload,
    PersonalizationProfile,
    PersonalizationResponse,
    canonical_hash,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.schemas.onboarding import FocusId, InvestmentMarketId, ScopeId
from infoscope.services.personalization import (
    PersonalizationError,
    PersonalizationRepository,
    PersonalizationRunner,
    cheap_prefilter,
)


def _profile(
    *,
    scopes: list[ScopeId] | None = None,
    markets: list[InvestmentMarketId] | None = None,
) -> PersonalizationProfile:
    return PersonalizationProfile(
        scope_ids=scopes or [ScopeId.AI],
        investment_market_ids=markets or [],
        focus_ids=[FocusId.DEEP_CONTEXT, FocusId.MAJOR_CHANGES],
    )


def _event(
    *,
    title: str = "New AI model released",
    display_time: datetime | None = None,
    ai_context: bool = True,
) -> PersonalizationEventInput:
    return PersonalizationEventInput(
        event_id=uuid4(),
        title=title,
        overview="A material change occurred.",
        state="developing",
        display_time=display_time or datetime(2026, 8, 16, tzinfo=UTC),
        updated_at=datetime(2026, 8, 16, 1, tzinfo=UTC),
        base_analysis=PersonalizationBaseAnalysis(
            base_analysis_id=uuid4(),
            summary=(
                "The release changes the model landscape."
                if ai_context
                else "The company published a routine update."
            ),
            event_type="technology.release",
            importance="high",
            topics=["AI" if ai_context else "Business"],
            entities=[
                BaseAnalysisEntity(
                    name="Example AI" if ai_context else "Example Company",
                    entity_type="company",
                )
            ],
        ),
    )


def test_prefilter_uses_token_boundaries_and_selected_investment_market() -> None:
    assert cheap_prefilter(_profile(), _event(title="An AI agent ships"))
    assert not cheap_prefilter(
        _profile(),
        _event(title="Said company reports earnings", ai_context=False),
    )

    china = _profile(
        scopes=[ScopeId.INVESTMENT],
        markets=[InvestmentMarketId.CHINA_MARKET],
    )
    assert cheap_prefilter(china, _event(title="中国市场股票估值变化"))
    assert not cheap_prefilter(
        china,
        _event(title="US stock market earnings on Nasdaq", ai_context=False),
    )
    assert cheap_prefilter(
        china,
        _event(title="Company earnings and valuation update", ai_context=False),
    )


def test_historical_profile_similarity_uses_the_complete_selection() -> None:
    target = _profile()
    exact = _profile()
    different_focus = exact.model_copy(update={"focus_ids": [FocusId.BREAKING_EVENTS]})
    different_scope = _profile(scopes=[ScopeId.TECHNOLOGY])

    exact_score = PersonalizationRepository._profile_similarity(target, exact)
    focus_score = PersonalizationRepository._profile_similarity(target, different_focus)
    scope_score = PersonalizationRepository._profile_similarity(target, different_scope)

    assert exact_score == 1
    assert exact_score > focus_score
    assert exact_score > scope_score


def test_input_requires_backend_display_order_and_hash_preserves_profile_order() -> None:
    newer = _event(display_time=datetime(2026, 8, 16, 2, tzinfo=UTC))
    older = _event(display_time=newer.display_time - timedelta(hours=1))
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=[newer, older])
    reversed_profile = value.model_copy(
        update={
            "profile": value.profile.model_copy(
                update={"focus_ids": list(reversed(value.profile.focus_ids))}
            )
        }
    )

    assert canonical_hash(value) != canonical_hash(reversed_profile)
    with pytest.raises(ValidationError, match="Backend display order"):
        PersonalizationInput(user_id=value.user_id, profile=value.profile, events=[older, newer])


def test_output_must_cover_input_and_preserve_saved_profile_order() -> None:
    event = _event()
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=[event])
    decision = PersonalizationDecision(
        event_id=event.event_id,
        relevant=True,
        priority="high",
        why_it_matters="This changes a selected area.",
        personalized_angle="Track the downstream technical impact.",
        matched_scope_ids=[ScopeId.AI],
        matched_focus_ids=[FocusId.DEEP_CONTEXT, FocusId.MAJOR_CHANGES],
        rationale="Matches the selected scope and focus.",
    )
    PersonalizationRepository.validate_output(
        PersonalizationPayload(decisions=[decision]),
        value,
    )
    wrong_order = decision.model_copy(
        update={"matched_focus_ids": list(reversed(decision.matched_focus_ids))}
    )
    with pytest.raises(PersonalizationError, match="PERSONALIZATION_SCHEMA_INVALID"):
        PersonalizationRepository.validate_output(
            PersonalizationPayload(decisions=[wrong_order]),
            value,
        )
    with pytest.raises(PersonalizationError, match="PERSONALIZATION_SCHEMA_INVALID"):
        PersonalizationRepository.validate_output(PersonalizationPayload(decisions=[]), value)


def test_irrelevant_decision_cannot_carry_public_personalization() -> None:
    with pytest.raises(ValidationError, match="cannot contain public personalization"):
        PersonalizationDecision(
            event_id=uuid4(),
            relevant=False,
            priority="low",
            why_it_matters="Must be absent",
            personalized_angle=None,
            matched_scope_ids=[],
            matched_focus_ids=[],
            rationale="Not relevant.",
        )


def test_strict_input_rejects_oversized_fields() -> None:
    event = _event()
    with pytest.raises(ValidationError, match="at most 512 characters"):
        PersonalizationEventInput.model_validate({**event.model_dump(), "title": "界" * 700})


@pytest.mark.asyncio
async def test_intelligence_adapter_uses_strict_personalization_prompt_and_schema() -> None:
    event = _event()
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=[event])

    async def handler(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.content)
        assert document["response_format"] == {"type": "json_object"}
        prompt = document["messages"][1]["content"]
        assert "personalization_input.v1" in prompt
        assert "json" in prompt
        assert "evidence" not in prompt.casefold()
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "personalization.v1",
                                    "decisions": [
                                        {
                                            "event_id": str(event.event_id),
                                            "relevant": True,
                                            "priority": "high",
                                            "why_it_matters": "Selected scope changed.",
                                            "personalized_angle": "Watch technical effects.",
                                            "matched_scope_ids": ["ai"],
                                            "matched_focus_ids": [
                                                "deep_context",
                                                "major_changes",
                                            ],
                                            "rationale": "Matches profile.",
                                        }
                                    ],
                                }
                            )
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    config = AnalysisConfig("https://api.example.com", "model", ("key",), 10, 0, 1024)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await DeepSeekIntelligenceClient(client=client, config=config).personalize(value)

    assert response.payload.decisions[0].event_id == event.event_id
    assert response.token_usage.total_tokens == 20


@pytest.mark.asyncio
async def test_running_user_attempt_cannot_be_claimed_twice() -> None:
    repository = PersonalizationRepository(None)  # type: ignore[arg-type]
    repository._locked_run = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(status="running")
    )

    with pytest.raises(PersonalizationError, match="PERSONALIZATION_ALREADY_RUNNING"):
        await repository.start_attempt(uuid4())


@pytest.mark.asyncio
async def test_empty_prefilter_persists_noop_without_model_call() -> None:
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=[])
    run = SimpleNamespace(
        id=uuid4(),
        status="pending",
        attempt_count=0,
        max_attempts=3,
    )

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
        async def personalize(self, _value):
            raise AssertionError("empty prefilter must not call the model")

    result = await PersonalizationRunner(  # type: ignore[arg-type]
        Repository(),
        NoModel(),
        max_attempts=3,
    ).run_user(value.user_id)

    assert result.status == "completed"


@pytest.mark.asyncio
async def test_cancelled_attempt_is_persisted_as_retryable_failure() -> None:
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=[_event()])
    run = SimpleNamespace(
        id=uuid4(),
        status="pending",
        attempt_count=0,
        max_attempts=3,
    )

    class Repository:
        async def input_snapshot(self, _user_id):
            return value

        async def create_or_reuse(self, _value, *, max_attempts):
            assert max_attempts == 3
            return run

        async def start_attempt(self, _run_id):
            run.status = "running"
            return run

        async def persist_failure(self, run_id, error_code, *, retryable):
            assert run_id == run.id
            assert error_code == "PERSONALIZATION_INTERRUPTED"
            assert retryable is True
            run.status = "pending"
            return run

    class CancelledModel:
        async def personalize(self, _value):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await PersonalizationRunner(  # type: ignore[arg-type]
            Repository(),
            CancelledModel(),
            max_attempts=3,
        ).run_user(value.user_id)

    assert run.status == "pending"


@pytest.mark.asyncio
async def test_terminal_failure_acknowledges_exact_queue_marker(monkeypatch) -> None:
    requested_at = datetime(2026, 8, 18, tzinfo=UTC)
    user_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        status="running",
        attempt_count=3,
        max_attempts=3,
        captured_update_requested_at=requested_at,
        active_slot=1,
        error_code=None,
        finished_at=None,
    )
    user = SimpleNamespace(
        id=user_id,
        personalization_update_requested_at=requested_at,
    )
    database = SimpleNamespace(
        rollback=AsyncMock(),
        get=AsyncMock(return_value=user),
        commit=AsyncMock(),
    )
    repository = PersonalizationRepository(database)
    monkeypatch.setattr(repository, "_locked_run", AsyncMock(return_value=run))

    result = await repository.persist_failure(
        run.id,
        "ANALYSIS_UPSTREAM_UNAVAILABLE",
        retryable=True,
    )

    assert result.status == "failed"
    assert result.active_slot is None
    assert user.personalization_update_requested_at is None
    database.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reused_terminal_failure_is_acknowledged_without_new_attempt() -> None:
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=[_event()])
    run = SimpleNamespace(
        id=uuid4(),
        status="failed",
        attempt_count=3,
        max_attempts=3,
    )
    acknowledged = False

    class Repository:
        async def input_snapshot(self, _user_id):
            return value

        async def create_or_reuse(self, _value, *, max_attempts):
            assert max_attempts == 3
            return run

        async def acknowledge_terminal_failure(self, _run):
            nonlocal acknowledged
            acknowledged = True

        async def start_attempt(self, _run_id):
            raise AssertionError("terminal run must not start another attempt")

    class NoModel:
        async def personalize(self, _value):
            raise AssertionError("terminal run must not call the model")

    result = await PersonalizationRunner(  # type: ignore[arg-type]
        Repository(),
        NoModel(),
        max_attempts=3,
    ).run_user(value.user_id)

    assert result.status == "failed"
    assert acknowledged is True


@pytest.mark.asyncio
async def test_personalization_batches_and_combines_complete_ordered_output() -> None:
    events = [
        _event(display_time=datetime(2026, 8, 16, 10 - index, tzinfo=UTC))
        for index in range(5)
    ]
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=events)
    run = SimpleNamespace(id=uuid4(), status="pending", attempt_count=0, max_attempts=3)

    class Repository:
        async def input_snapshot(self, _user_id):
            return value

        async def create_or_reuse(self, _value, *, max_attempts):
            return run

        async def start_attempt(self, _run_id):
            run.status = "running"
            return run

        async def persist_success(self, _run_id, original, response):
            assert original == value
            assert [item.event_id for item in response.payload.decisions] == [
                item.event_id for item in events
            ]
            assert response.token_usage.total_tokens == 15
            run.status = "completed"
            return run

    class BatchedModel:
        calls: list[list] = []
        active = 0
        max_active = 0

        async def personalize(self, batch):
            self.calls.append([event.event_id for event in batch.events])
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return PersonalizationResponse(
                payload=PersonalizationPayload(
                    decisions=[
                        PersonalizationDecision(
                            event_id=event.event_id,
                            relevant=False,
                            priority="low",
                            why_it_matters=None,
                            personalized_angle=None,
                            matched_scope_ids=[],
                            matched_focus_ids=[],
                            rationale="Not relevant to this profile.",
                        )
                        for event in batch.events
                    ]
                ),
                provider="provider",
                model="model",
                token_usage=TokenUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
            )

    client = BatchedModel()
    result = await PersonalizationRunner(  # type: ignore[arg-type]
        Repository(),
        client,
        max_attempts=3,
        batch_size=2,
        batch_concurrency=2,
    ).run_user(value.user_id)

    assert result.status == "completed"
    assert [len(batch) for batch in client.calls] == [2, 2, 1]
    assert client.max_active == 2


@pytest.mark.asyncio
async def test_request_rejection_is_terminal_and_cancels_sibling_batches() -> None:
    events = [
        _event(display_time=datetime(2026, 8, 16, 10 - index, tzinfo=UTC))
        for index in range(2)
    ]
    value = PersonalizationInput(user_id=uuid4(), profile=_profile(), events=events)
    run = SimpleNamespace(id=uuid4(), status="pending", attempt_count=0, max_attempts=3)

    class Repository:
        async def input_snapshot(self, _user_id):
            return value

        async def create_or_reuse(self, _value, *, max_attempts):
            return run

        async def start_attempt(self, _run_id):
            run.status = "running"
            return run

        async def persist_failure(self, _run_id, error_code, *, retryable):
            assert error_code == "ANALYSIS_REQUEST_REJECTED"
            assert retryable is False
            run.status = "failed"
            return run

    class RejectingModel:
        calls = 0
        sibling_cancelled = False

        async def personalize(self, _batch):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0)
                raise AnalysisError("ANALYSIS_REQUEST_REJECTED")
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                self.sibling_cancelled = True
                raise

    client = RejectingModel()
    result = await PersonalizationRunner(  # type: ignore[arg-type]
        Repository(),
        client,
        max_attempts=3,
        batch_size=1,
        batch_concurrency=2,
    ).run_user(value.user_id)

    assert result.status == "failed"
    assert client.sibling_cancelled is True
