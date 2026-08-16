from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.intelligence_schemas import (
    ConflictAnalysisPayload,
    ConflictClaimInput,
    ConflictEvidenceSignal,
    EventConflictInput,
    ExistingConflictCandidate,
)
from infoscope.models import Claim, Event, Signal
from infoscope.services.claims_timeline import (
    ConflictAnalysisRunner,
    IntelligenceError,
    IntelligenceRepository,
)


def _evidence(signal_id):
    return ConflictEvidenceSignal(
        signal_id=signal_id,
        published_at=None,
        sanitized_text="Sanitized evidence",
        public_safe_provenance=None,
    )


def _event(event_id, claims):
    return EventConflictInput(
        event_id=event_id,
        title="Event",
        overview="Overview",
        state="developing",
        claims=claims,
    )


def _claim(event_id, claim_id, signal_ids=()):
    return ConflictClaimInput(
        claim_id=claim_id,
        event_id=event_id,
        text="Claim",
        state="unresolved",
        evidence_signals=[_evidence(value) for value in signal_ids],
    )


def test_conflict_payload_requires_evidence_for_single_claim() -> None:
    with pytest.raises(ValidationError, match="single-claim conflict"):
        ConflictAnalysisPayload.model_validate(
            {
                "new_conflicts": [
                    {
                        "decision_key": "single",
                        "event_id": uuid4(),
                        "summary": "Conflict",
                        "claim_ids": [uuid4()],
                        "evidence_signal_ids": [],
                        "rationale": "Semantic contradiction",
                    }
                ],
                "existing_conflict_updates": [],
                "unconflicted_claim_ids": [],
            }
        )


def test_conflict_validation_rejects_same_event_evidence_from_unselected_claim() -> None:
    event_id, selected_claim, other_claim, other_signal = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    events = [
        _event(
            event_id,
            [
                _claim(event_id, selected_claim),
                _claim(event_id, other_claim, [other_signal]),
            ],
        )
    ]
    payload = ConflictAnalysisPayload.model_validate(
        {
            "new_conflicts": [
                {
                    "decision_key": "wrong-evidence",
                    "event_id": event_id,
                    "summary": "Conflict",
                    "claim_ids": [selected_claim],
                    "evidence_signal_ids": [other_signal],
                    "rationale": "Semantic contradiction",
                }
            ],
            "existing_conflict_updates": [],
            "unconflicted_claim_ids": [other_claim],
        }
    )

    with pytest.raises(IntelligenceError, match="CONFLICT_EVIDENCE_INVALID"):
        ConflictAnalysisRunner._validate(payload, events, [])


def test_existing_conflict_update_uses_append_only_effective_structure() -> None:
    event_id, claim_id, signal_id, conflict_id = uuid4(), uuid4(), uuid4(), uuid4()
    events = [_event(event_id, [_claim(event_id, claim_id, [signal_id])])]
    candidate = ExistingConflictCandidate(
        conflict_id=conflict_id,
        event_id=event_id,
        summary="Historical conflict",
        claim_ids=[claim_id],
        evidence_signal_ids=[signal_id],
    )
    payload = ConflictAnalysisPayload.model_validate(
        {
            "new_conflicts": [],
            "existing_conflict_updates": [
                {
                    "decision_key": "append",
                    "existing_conflict_id": conflict_id,
                    "event_id": event_id,
                    "summary": "Updated summary",
                    "claim_ids": [claim_id],
                    "evidence_signal_ids": [],
                    "rationale": "Existing Evidence remains attached",
                }
            ],
            "unconflicted_claim_ids": [],
        }
    )

    ConflictAnalysisRunner._validate(payload, events, [candidate])


def test_unconflicted_claim_does_not_have_to_update_historical_conflict() -> None:
    event_id, claim_id, signal_id = uuid4(), uuid4(), uuid4()
    events = [_event(event_id, [_claim(event_id, claim_id, [signal_id])])]
    candidate = ExistingConflictCandidate(
        conflict_id=uuid4(),
        event_id=event_id,
        summary="Historical conflict",
        claim_ids=[claim_id],
        evidence_signal_ids=[signal_id],
    )
    payload = ConflictAnalysisPayload.model_validate(
        {
            "new_conflicts": [],
            "existing_conflict_updates": [],
            "unconflicted_claim_ids": [claim_id],
        }
    )

    ConflictAnalysisRunner._validate(payload, events, [candidate])


def test_conflict_validation_requires_complete_claim_coverage() -> None:
    event_id, first_claim, second_claim = uuid4(), uuid4(), uuid4()
    events = [
        _event(
            event_id,
            [_claim(event_id, first_claim), _claim(event_id, second_claim)],
        )
    ]
    payload = ConflictAnalysisPayload.model_validate(
        {
            "new_conflicts": [],
            "existing_conflict_updates": [],
            "unconflicted_claim_ids": [first_claim],
        }
    )

    with pytest.raises(IntelligenceError, match="CONFLICT_CLAIM_COVERAGE_INVALID"):
        ConflictAnalysisRunner._validate(payload, events, [])


def test_conflict_signal_rejects_private_public_provenance_before_model() -> None:
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
        IntelligenceRepository._conflict_signal(signal)


async def test_backend_applies_one_way_conflict_states() -> None:
    event_id = uuid4()
    unresolved = Claim(id=uuid4(), event_id=event_id, text="One", state="unresolved")
    contradicted = Claim(id=uuid4(), event_id=event_id, text="Two", state="contradicted")
    event = Event(
        id=event_id,
        title="Event",
        overview="Overview",
        state="confirmed",
        display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
    )

    class Result:
        def scalars(self):
            return [unresolved, contradicted]

    class Database:
        async def get(self, model, identifier):
            if model is Event and identifier == event_id:
                return event
            return None

        async def execute(self, _statement):
            return Result()

    repository = IntelligenceRepository(Database())  # type: ignore[arg-type]
    await repository._apply_conflict_states({event_id: {unresolved.id, contradicted.id}})

    assert unresolved.state == "conflicting"
    assert contradicted.state == "contradicted"
    assert event.state == "conflicting"
