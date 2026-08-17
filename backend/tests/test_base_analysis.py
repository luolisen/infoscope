from datetime import UTC, datetime
from types import MethodType
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.intelligence_schemas import (
    BaseAnalysisContent,
    BaseAnalysisPayload,
    BaseAnalysisResponse,
    ConflictAnalysisArtifact,
    ConflictAnalysisPayload,
    EventBaseAnalysisInput,
    ExistingBaseAnalysisCandidate,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.models import BaseAnalysis, PipelineArtifact, Signal
from infoscope.services.base_analysis import BaseAnalysisRepository, BaseAnalysisRunner
from infoscope.services.claims_timeline import IntelligenceError


def _event(event_id):
    return EventBaseAnalysisInput(
        event_id=event_id,
        title="Event",
        overview="Overview",
        state="developing",
        display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
        claims=[],
        timeline=[],
        conflicts=[],
        evidence_signals=[],
    )


def _decision(event_id, **overrides):
    value = {
        "decision_key": "base",
        "event_id": event_id,
        "summary": "Current factual summary",
        "event_type": "technology.release",
        "importance": "high",
        "topics": ["AI"],
        "entities": [{"name": "Example Corp", "entity_type": "organization"}],
        "rationale": "Derived from the persisted fact layer",
    }
    value.update(overrides)
    return value


def test_base_analysis_normalizes_topics_and_rejects_duplicate_entities() -> None:
    content = BaseAnalysisContent.model_validate(
        {
            "summary": "  Summary  ",
            "event_type": "technology.release",
            "importance": "medium",
            "topics": [" AI "],
            "entities": [],
        }
    )
    assert content.summary == "Summary"
    assert content.topics == ["AI"]

    with pytest.raises(ValidationError, match="entities must be unique"):
        BaseAnalysisContent.model_validate(
            {
                "summary": "Summary",
                "event_type": "technology.release",
                "importance": "medium",
                "topics": [],
                "entities": [
                    {"name": "Example Corp", "entity_type": "organization"},
                    {"name": "example corp", "entity_type": "organization"},
                ],
            }
        )


def test_base_analysis_validation_requires_exact_event_and_candidate_coverage() -> None:
    new_event_id, existing_event_id, analysis_id = uuid4(), uuid4(), uuid4()
    events = [_event(new_event_id), _event(existing_event_id)]
    candidate = ExistingBaseAnalysisCandidate(
        base_analysis_id=analysis_id,
        event_id=existing_event_id,
        summary="Old",
        event_type="technology.release",
        importance="medium",
        topics=[],
        entities=[],
    )
    valid = BaseAnalysisPayload.model_validate(
        {
            "new_analyses": [_decision(new_event_id)],
            "existing_analysis_updates": [
                _decision(
                    existing_event_id,
                    decision_key="update",
                    existing_base_analysis_id=analysis_id,
                )
            ],
        }
    )
    BaseAnalysisRunner._validate(valid, events, [candidate])

    incomplete = BaseAnalysisPayload.model_validate(
        {"new_analyses": [_decision(new_event_id)], "existing_analysis_updates": []}
    )
    with pytest.raises(IntelligenceError, match="BASE_ANALYSIS_EVENT_COVERAGE_INVALID"):
        BaseAnalysisRunner._validate(incomplete, events, [candidate])


def test_base_analysis_decision_type_is_derived_from_backend_candidates() -> None:
    new_event_id, existing_event_id, analysis_id = uuid4(), uuid4(), uuid4()
    candidate = ExistingBaseAnalysisCandidate(
        base_analysis_id=analysis_id,
        event_id=existing_event_id,
        summary="Old",
        event_type="technology.release",
        importance="medium",
        topics=[],
        entities=[],
    )
    response = BaseAnalysisResponse(
        payload=BaseAnalysisPayload.model_validate(
            {
                "new_analyses": [
                    _decision(existing_event_id, decision_key="wrong-new")
                ],
                "existing_analysis_updates": [
                    _decision(
                        new_event_id,
                        decision_key="wrong-update",
                        existing_base_analysis_id=uuid4(),
                    )
                ],
            }
        ),
        provider="test",
        model="test",
        token_usage=TokenUsage(),
    )

    normalized = BaseAnalysisRunner._normalize_decision_types(response, [candidate])
    BaseAnalysisRunner._validate(
        normalized.payload,
        [_event(new_event_id), _event(existing_event_id)],
        [candidate],
    )

    assert [item.event_id for item in normalized.payload.new_analyses] == [new_event_id]
    assert normalized.payload.existing_analysis_updates[0].event_id == existing_event_id
    assert (
        normalized.payload.existing_analysis_updates[0].existing_base_analysis_id
        == analysis_id
    )


async def test_source_events_include_unconflicted_claims_without_assignments() -> None:
    claim_id, event_id, source_id = uuid4(), uuid4(), uuid4()
    artifact = ConflictAnalysisArtifact(
        source_artifact_id=source_id,
        model_output=ConflictAnalysisPayload(
            new_conflicts=[],
            existing_conflict_updates=[],
            unconflicted_claim_ids=[claim_id],
        ),
        assignments=[],
    )

    class Repository:
        async def event_ids_for_unconflicted_claims(self, claim_ids):
            assert claim_ids == {claim_id}
            return {event_id}

    runner = BaseAnalysisRunner(
        repository=Repository(),  # type: ignore[arg-type]
        pipeline=object(),  # type: ignore[arg-type]
        client=object(),  # type: ignore[arg-type]
    )
    assert await runner._source_event_ids(artifact) == {event_id}


async def test_empty_source_returns_canonical_noop_without_model_call() -> None:
    class Client:
        called = False

        async def analyze_base(self, **_kwargs):
            self.called = True
            raise AssertionError("model must not be called")

    client = Client()
    runner = BaseAnalysisRunner(
        repository=object(),  # type: ignore[arg-type]
        pipeline=object(),  # type: ignore[arg-type]
        client=client,
    )
    response = await runner._response([], [])

    assert not client.called
    assert response.provider == "backend"
    assert response.model == "no-op"
    assert response.payload.new_analyses == []
    assert response.payload.existing_analysis_updates == []


async def test_existing_analysis_is_fully_replaced_without_changing_event_state() -> None:
    event_id, analysis_id, source_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    existing = BaseAnalysis(
        id=analysis_id,
        event_id=event_id,
        source_artifact_id=uuid4(),
        summary="Old",
        event_type="old.type",
        importance="low",
        topics=["Old"],
        entities=[],
    )

    class Database:
        def __init__(self):
            self.added = []

        async def get(self, model, identifier):
            if model is BaseAnalysis and identifier == analysis_id:
                return existing
            return None

        def add(self, value):
            self.added.append(value)

    database = Database()
    repository = BaseAnalysisRepository(database)  # type: ignore[arg-type]

    async def commit_or_reuse(self, *_args):
        return 0, 1, 0, False

    repository._commit_or_reuse = MethodType(commit_or_reuse, repository)  # type: ignore[method-assign]
    response = BaseAnalysisResponse(
        payload=BaseAnalysisPayload.model_validate(
            {
                "new_analyses": [],
                "existing_analysis_updates": [
                    _decision(
                        event_id,
                        existing_base_analysis_id=analysis_id,
                        summary="New",
                        importance="critical",
                        topics=["AI"],
                    )
                ],
            }
        ),
        provider="deepseek",
        model="test",
        token_usage=TokenUsage(),
    )
    run = type("Run", (), {"id": run_id})()
    candidate = ExistingBaseAnalysisCandidate(
        base_analysis_id=analysis_id,
        event_id=event_id,
        summary="Old",
        event_type="old.type",
        importance="low",
        topics=["Old"],
        entities=[],
    )

    result = await repository.persist(
        run=run,  # type: ignore[arg-type]
        source_artifact_id=source_id,
        input_hash="a" * 64,
        response=response,
        candidates={analysis_id: candidate},
    )

    assert result == (0, 1, 0, False)
    assert existing.source_artifact_id == source_id
    assert existing.summary == "New"
    assert existing.importance == "critical"
    assert existing.topics == ["AI"]
    assert any(isinstance(value, PipelineArtifact) for value in database.added)


def test_base_analysis_rejects_private_provenance_before_model() -> None:
    signal = Signal(
        id=uuid4(),
        raw_information_id=uuid4(),
        signal_index=0,
        title="Private",
        normalized_text="Sanitized",
        source_type="telegram",
        evidence_visibility="private_sanitized",
        public_provenance={"username": "forbidden"},
        content_hash="a" * 64,
    )

    with pytest.raises(IntelligenceError, match="INTELLIGENCE_PRIVATE_PROVENANCE_INVALID"):
        BaseAnalysisRepository._evidence_signal(signal)
