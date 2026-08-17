from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.intelligence_schemas import (
    ClaimExtractionPayload,
    ClaimExtractionResponse,
    ClaimTimelineInput,
    ConflictAnalysisPayload,
    ConflictAnalysisResponse,
    ConflictClaimInput,
    EventClaimInput,
    EventConflictInput,
    EventTimelineInput,
    ExistingClaimCandidate,
    ExistingTimelineCandidate,
    TimelineReconstructionPayload,
    TimelineReconstructionResponse,
)
from infoscope.analysis.schemas import AnalysisSignal
from infoscope.models import Claim, Event, Signal
from infoscope.services.claims_timeline import (
    ClaimExtractionRunner,
    ConflictAnalysisRunner,
    IntelligenceError,
    IntelligenceRepository,
    TimelineReconstructionRunner,
)


def _signal(signal_id, *, private=False, provenance=None) -> AnalysisSignal:
    return AnalysisSignal(
        signal_id=signal_id,
        title="Evidence",
        text="Evidence text",
        published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        source_type="telegram" if private else "web",
        evidence_visibility="private_sanitized" if private else "public",
        public_provenance=provenance,
    )


def test_claim_payload_allows_one_signal_to_support_multiple_claims() -> None:
    event_id, signal_id = uuid4(), uuid4()
    payload = ClaimExtractionPayload.model_validate(
        {
            "new_claims": [
                {
                    "decision_key": "one",
                    "event_id": event_id,
                    "text": "One",
                    "evidence_signal_ids": [signal_id],
                    "rationale": "Evidence",
                },
                {
                    "decision_key": "two",
                    "event_id": event_id,
                    "text": "Two",
                    "evidence_signal_ids": [signal_id],
                    "rationale": "Evidence",
                },
            ],
            "existing_claim_updates": [],
            "unused_signal_ids": [],
        }
    )
    assert len(payload.new_claims) == 2


def test_claim_model_cannot_set_state() -> None:
    with pytest.raises(ValidationError):
        ClaimExtractionPayload.model_validate(
            {
                "new_claims": [
                    {
                        "decision_key": "one",
                        "event_id": uuid4(),
                        "text": "One",
                        "state": "confirmed",
                        "evidence_signal_ids": [uuid4()],
                        "rationale": "Evidence",
                    }
                ],
                "existing_claim_updates": [],
                "unused_signal_ids": [],
            }
        )


def test_claim_validation_requires_complete_event_scoped_evidence() -> None:
    event_id, other_event_id, signal_id = uuid4(), uuid4(), uuid4()
    events = [
        EventClaimInput(
            event_id=event_id, title="Event", overview="Overview", signals=[_signal(signal_id)]
        )
    ]
    payload = ClaimExtractionPayload.model_validate(
        {
            "new_claims": [
                {
                    "decision_key": "one",
                    "event_id": other_event_id,
                    "text": "One",
                    "evidence_signal_ids": [signal_id],
                    "rationale": "Evidence",
                }
            ],
            "existing_claim_updates": [],
            "unused_signal_ids": [],
        }
    )
    with pytest.raises(IntelligenceError, match="CLAIM_EVIDENCE_INVALID"):
        ClaimExtractionRunner._validate(payload, events, [])


def test_claim_validation_rejects_unknown_existing_claim() -> None:
    event_id, signal_id = uuid4(), uuid4()
    events = [
        EventClaimInput(
            event_id=event_id, title="Event", overview="Overview", signals=[_signal(signal_id)]
        )
    ]
    payload = ClaimExtractionPayload.model_validate(
        {
            "new_claims": [],
            "existing_claim_updates": [
                {
                    "decision_key": "update",
                    "event_id": event_id,
                    "existing_claim_id": uuid4(),
                    "text": "Updated",
                    "evidence_signal_ids": [signal_id],
                    "rationale": "Evidence",
                }
            ],
            "unused_signal_ids": [],
        }
    )
    candidate = ExistingClaimCandidate(
        claim_id=uuid4(), event_id=event_id, text="Old", state="unresolved", evidence_signal_ids=[]
    )
    with pytest.raises(IntelligenceError, match="CLAIM_OUTSIDE_CANDIDATES"):
        ClaimExtractionRunner._validate(payload, events, [candidate])


def test_incremental_claim_update_allows_candidate_and_current_evidence() -> None:
    event_id, current_signal_id, historical_signal_id, claim_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    events = [
        EventClaimInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            signals=[_signal(current_signal_id)],
        )
    ]
    candidate = ExistingClaimCandidate(
        claim_id=claim_id,
        event_id=event_id,
        text="Old",
        state="unresolved",
        evidence_signal_ids=[historical_signal_id],
    )
    response = ClaimExtractionResponse(
        payload=ClaimExtractionPayload.model_validate(
            {
                "new_claims": [],
                "existing_claim_updates": [
                    {
                        "decision_key": "update",
                        "event_id": event_id,
                        "existing_claim_id": claim_id,
                        "text": "Updated",
                        "evidence_signal_ids": [historical_signal_id, current_signal_id],
                        "rationale": "New evidence",
                    },
                    {
                        "decision_key": "unknown-target",
                        "event_id": event_id,
                        "existing_claim_id": uuid4(),
                        "text": "Drop",
                        "evidence_signal_ids": [current_signal_id],
                        "rationale": "Unknown candidate",
                    }
                ],
                "unused_signal_ids": [],
            }
        ),
        provider="test",
        model="test",
        token_usage={},
    )

    normalized = ClaimExtractionRunner._normalize_decisions(response, events, [candidate])
    normalized = ClaimExtractionRunner._normalize_coverage(normalized, events)
    ClaimExtractionRunner._validate(normalized.payload, events, [candidate])

    assert normalized.payload.unused_signal_ids == []
    assert [
        item.existing_claim_id for item in normalized.payload.existing_claim_updates
    ] == [claim_id]


def test_incremental_new_claims_filter_historical_evidence_and_drop_empty_decisions() -> None:
    event_id, current_signal_id, historical_signal_id = uuid4(), uuid4(), uuid4()
    events = [
        EventClaimInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            signals=[_signal(current_signal_id)],
        )
    ]
    response = ClaimExtractionResponse(
        payload=ClaimExtractionPayload.model_validate(
            {
                "new_claims": [
                    {
                        "decision_key": "mixed",
                        "event_id": event_id,
                        "text": "Grounded",
                        "evidence_signal_ids": [historical_signal_id, current_signal_id],
                        "rationale": "Mixed",
                    },
                    {
                        "decision_key": "historical-only",
                        "event_id": event_id,
                        "text": "Drop",
                        "evidence_signal_ids": [historical_signal_id],
                        "rationale": "No current evidence",
                    },
                ],
                "existing_claim_updates": [],
                "unused_signal_ids": [],
            }
        ),
        provider="test",
        model="test",
        token_usage={},
    )

    normalized = ClaimExtractionRunner._normalize_decisions(response, events, [])

    assert [item.decision_key for item in normalized.payload.new_claims] == ["mixed"]
    assert normalized.payload.new_claims[0].evidence_signal_ids == [current_signal_id]


def test_timeline_validation_requires_aware_time_and_same_event_claims() -> None:
    event_id, claim_id = uuid4(), uuid4()
    events = [
        EventTimelineInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            state="developing",
            display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
            claims=[
                ClaimTimelineInput(
                    claim_id=claim_id,
                    event_id=event_id,
                    text="Claim",
                    state="unresolved",
                    evidence_signals=[_signal(uuid4())],
                )
            ],
        )
    ]
    payload = TimelineReconstructionPayload.model_validate(
        {
            "new_entries": [
                {
                    "decision_key": "first",
                    "event_id": event_id,
                    "occurred_at": "2026-08-16T09:00:00",
                    "summary": "First",
                    "claim_ids": [claim_id],
                    "rationale": "Change",
                }
            ],
            "existing_entry_updates": [],
            "unused_claim_ids": [],
        }
    )
    with pytest.raises(IntelligenceError, match="TIMELINE_OCCURRED_AT_INVALID"):
        TimelineReconstructionRunner._validate(payload, events, [])


def test_timeline_validation_rejects_unknown_update_candidate() -> None:
    event_id, claim_id = uuid4(), uuid4()
    events = [
        EventTimelineInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            state="developing",
            display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
            claims=[
                ClaimTimelineInput(
                    claim_id=claim_id,
                    event_id=event_id,
                    text="Claim",
                    state="unresolved",
                    evidence_signals=[],
                )
            ],
        )
    ]
    payload = TimelineReconstructionPayload.model_validate(
        {
            "new_entries": [],
            "existing_entry_updates": [
                {
                    "decision_key": "update",
                    "event_id": event_id,
                    "existing_timeline_entry_id": uuid4(),
                    "occurred_at": "2026-08-16T09:00:00Z",
                    "summary": "Updated",
                    "claim_ids": [claim_id],
                    "rationale": "Change",
                }
            ],
            "unused_claim_ids": [],
        }
    )
    candidate = ExistingTimelineCandidate(
        timeline_entry_id=uuid4(),
        event_id=event_id,
        occurred_at=datetime(2026, 8, 16, 8, tzinfo=UTC),
        summary="Old",
        claim_ids=[],
    )
    with pytest.raises(IntelligenceError, match="TIMELINE_OUTSIDE_CANDIDATES"):
        TimelineReconstructionRunner._validate(payload, events, [candidate])


def test_timeline_decisions_filter_cross_event_claims_and_drop_empty_entries() -> None:
    event_id, claim_id, other_claim_id = uuid4(), uuid4(), uuid4()
    events = [
        EventTimelineInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            state="developing",
            display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
            claims=[
                ClaimTimelineInput(
                    claim_id=claim_id,
                    event_id=event_id,
                    text="Claim",
                    state="unresolved",
                    evidence_signals=[],
                )
            ],
        )
    ]
    response = TimelineReconstructionResponse(
        payload=TimelineReconstructionPayload.model_validate(
            {
                "new_entries": [
                    {
                        "decision_key": "mixed",
                        "event_id": event_id,
                        "occurred_at": "2026-08-16T09:00:00Z",
                        "summary": "Grounded",
                        "claim_ids": [other_claim_id, claim_id],
                        "rationale": "Mixed",
                    },
                    {
                        "decision_key": "wrong-only",
                        "event_id": event_id,
                        "occurred_at": "2026-08-16T09:01:00Z",
                        "summary": "Drop",
                        "claim_ids": [other_claim_id],
                        "rationale": "Wrong event",
                    },
                ],
                "existing_entry_updates": [],
                "unused_claim_ids": [],
            }
        ),
        provider="test",
        model="test",
        token_usage={},
    )

    normalized = TimelineReconstructionRunner._normalize_decisions(response, events, [])

    assert [item.decision_key for item in normalized.payload.new_entries] == ["mixed"]
    assert normalized.payload.new_entries[0].claim_ids == [claim_id]


def test_conflict_decisions_filter_cross_event_relations_and_drop_invalid_items() -> None:
    event_id, claim_id, other_claim_id, signal_id, other_signal_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    events = [
        EventConflictInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            state="developing",
            claims=[
                ConflictClaimInput(
                    claim_id=claim_id,
                    event_id=event_id,
                    text="Claim",
                    state="unresolved",
                    evidence_signals=[
                        {
                            "signal_id": signal_id,
                            "published_at": None,
                            "sanitized_text": "Evidence",
                            "public_safe_provenance": None,
                        }
                    ],
                )
            ],
        )
    ]
    response = ConflictAnalysisResponse(
        payload=ConflictAnalysisPayload.model_validate(
            {
                "new_conflicts": [
                    {
                        "decision_key": "mixed",
                        "event_id": event_id,
                        "summary": "Grounded",
                        "claim_ids": [other_claim_id, claim_id],
                        "evidence_signal_ids": [other_signal_id, signal_id],
                        "rationale": "Mixed",
                    },
                    {
                        "decision_key": "wrong-only",
                        "event_id": event_id,
                        "summary": "Drop",
                        "claim_ids": [other_claim_id],
                        "evidence_signal_ids": [other_signal_id],
                        "rationale": "Wrong event",
                    },
                ],
                "existing_conflict_updates": [],
                "unconflicted_claim_ids": [],
            }
        ),
        provider="test",
        model="test",
        token_usage={},
    )

    normalized = ConflictAnalysisRunner._normalize_decisions(response, events, [])

    assert [item.decision_key for item in normalized.payload.new_conflicts] == ["mixed"]
    assert normalized.payload.new_conflicts[0].claim_ids == [claim_id]
    assert normalized.payload.new_conflicts[0].evidence_signal_ids == [signal_id]


def test_backend_derives_claim_timeline_and_conflict_coverage_complements() -> None:
    event_id, signal_id, claim_id = uuid4(), uuid4(), uuid4()
    claim_events = [
        EventClaimInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            signals=[_signal(signal_id)],
        )
    ]
    claim_response = ClaimExtractionResponse(
        payload=ClaimExtractionPayload(
            new_claims=[], existing_claim_updates=[], unused_signal_ids=[]
        ),
        provider="test",
        model="test",
        token_usage={},
    )
    normalized_claims = ClaimExtractionRunner._normalize_coverage(
        claim_response, claim_events
    )
    assert normalized_claims.payload.unused_signal_ids == [signal_id]

    timeline_claim = ClaimTimelineInput(
        claim_id=claim_id,
        event_id=event_id,
        text="Claim",
        state="unresolved",
        evidence_signals=[_signal(signal_id)],
    )
    timeline_events = [
        EventTimelineInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            state="developing",
            display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
            claims=[timeline_claim],
        )
    ]
    timeline_response = TimelineReconstructionResponse(
        payload=TimelineReconstructionPayload(
            new_entries=[], existing_entry_updates=[], unused_claim_ids=[]
        ),
        provider="test",
        model="test",
        token_usage={},
    )
    normalized_timeline = TimelineReconstructionRunner._normalize_coverage(
        timeline_response, timeline_events
    )
    assert normalized_timeline.payload.unused_claim_ids == [claim_id]

    conflict_events = [
        EventConflictInput(
            event_id=event_id,
            title="Event",
            overview="Overview",
            state="developing",
            claims=[
                ConflictClaimInput(
                    claim_id=claim_id,
                    event_id=event_id,
                    text="Claim",
                    state="unresolved",
                    evidence_signals=[],
                )
            ],
        )
    ]
    conflict_response = ConflictAnalysisResponse(
        payload=ConflictAnalysisPayload(
            new_conflicts=[],
            existing_conflict_updates=[],
            unconflicted_claim_ids=[],
        ),
        provider="test",
        model="test",
        token_usage={},
    )
    normalized_conflicts = ConflictAnalysisRunner._normalize_coverage(
        conflict_response, conflict_events
    )
    assert normalized_conflicts.payload.unconflicted_claim_ids == [claim_id]


async def test_claim_inputs_preserve_incremental_signal_order() -> None:
    event_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    event = Event(
        id=event_id,
        title="Event",
        overview="Overview",
        state="developing",
        display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
    )

    def stored_signal(signal_id, index):
        return Signal(
            id=signal_id,
            raw_information_id=uuid4(),
            signal_index=index,
            title=f"Signal {index}",
            normalized_text=f"Evidence {index}",
            source_type="web",
            evidence_visibility="public",
            public_provenance=None,
            content_hash=f"{index:x}" * 64,
        )

    first = stored_signal(first_id, 1)
    second = stored_signal(second_id, 2)

    class Result:
        def __init__(self, *, scalar_values=None, rows=None):
            self.scalar_values = scalar_values or []
            self.rows = rows or []

        def scalars(self):
            return self.scalar_values

        def all(self):
            return self.rows

    class Database:
        def __init__(self):
            self.results = iter(
                [
                    Result(scalar_values=[event]),
                    Result(rows=[(event_id, first), (event_id, second)]),
                    Result(scalar_values=[]),
                ]
            )

        async def execute(self, _statement):
            return next(self.results)

    repository = IntelligenceRepository(Database())  # type: ignore[arg-type]
    events, candidates = await repository.claim_inputs(
        {event_id}, signal_ids=[second_id, first_id]
    )

    assert candidates == []
    assert [item.signal_id for item in events[0].signals] == [second_id, first_id]


async def test_timeline_input_rejects_private_public_provenance_before_model() -> None:
    event_id, claim_id, signal_id = uuid4(), uuid4(), uuid4()
    event = Event(
        id=event_id,
        title="Event",
        overview="Overview",
        state="developing",
        display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
    )
    claim = Claim(id=claim_id, event_id=event_id, text="Claim", state="unresolved")
    signal = Signal(
        id=signal_id,
        raw_information_id=uuid4(),
        signal_index=0,
        title="Private",
        normalized_text="Sanitized",
        source_type="telegram",
        evidence_visibility="private_sanitized",
        public_provenance={"username": "forbidden"},
        content_hash="b" * 64,
    )

    class Result:
        def __init__(self, *, scalar_values=None, rows=None):
            self.scalar_values = scalar_values or []
            self.rows = rows or []

        def scalars(self):
            return self.scalar_values

        def all(self):
            return self.rows

    class Database:
        def __init__(self):
            self.results = iter(
                [
                    Result(scalar_values=[event]),
                    Result(scalar_values=[claim]),
                    Result(rows=[(claim_id, signal)]),
                    Result(rows=[(event_id, signal_id)]),
                ]
            )

        async def execute(self, _statement):
            return next(self.results)

    repository = IntelligenceRepository(Database())  # type: ignore[arg-type]
    with pytest.raises(IntelligenceError, match="INTELLIGENCE_PRIVATE_PROVENANCE_INVALID"):
        await repository.timeline_inputs({event_id})


async def test_timeline_input_rejects_claim_evidence_outside_event() -> None:
    event_id, other_event_id, claim_id, signal_id = uuid4(), uuid4(), uuid4(), uuid4()
    event = Event(
        id=event_id,
        title="Event",
        overview="Overview",
        state="developing",
        display_time=datetime(2026, 8, 16, 9, tzinfo=UTC),
    )
    claim = Claim(id=claim_id, event_id=event_id, text="Claim", state="unresolved")
    signal = Signal(
        id=signal_id,
        raw_information_id=uuid4(),
        signal_index=0,
        title="Evidence",
        normalized_text="Evidence text",
        source_type="web",
        evidence_visibility="public",
        public_provenance={"platform": "web"},
        content_hash="a" * 64,
    )

    class Result:
        def __init__(self, *, scalar_values=None, rows=None):
            self.scalar_values = scalar_values or []
            self.rows = rows or []

        def scalars(self):
            return self.scalar_values

        def all(self):
            return self.rows

    class Database:
        def __init__(self):
            self.results = iter(
                [
                    Result(scalar_values=[event]),
                    Result(scalar_values=[claim]),
                    Result(rows=[(claim_id, signal)]),
                    Result(rows=[(other_event_id, signal_id)]),
                ]
            )

        async def execute(self, _statement):
            return next(self.results)

    repository = IntelligenceRepository(Database())  # type: ignore[arg-type]
    with pytest.raises(IntelligenceError, match="TIMELINE_EVIDENCE_OUTSIDE_EVENT"):
        await repository.timeline_inputs({event_id})
