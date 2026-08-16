from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infoscope.analysis.intelligence_schemas import (
    ClaimExtractionPayload,
    ClaimTimelineInput,
    EventClaimInput,
    ExistingClaimCandidate,
    ExistingTimelineCandidate,
    TimelineReconstructionPayload,
)
from infoscope.analysis.schemas import AnalysisSignal
from infoscope.services.claims_timeline import (
    ClaimExtractionRunner,
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


def test_timeline_validation_requires_aware_time_and_same_event_claims() -> None:
    event_id, claim_id = uuid4(), uuid4()
    claims = [
        ClaimTimelineInput(
            claim_id=claim_id,
            event_id=event_id,
            text="Claim",
            state="unresolved",
            evidence_signal_ids=[uuid4()],
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
        TimelineReconstructionRunner._validate(payload, claims, [])


def test_timeline_validation_rejects_unknown_update_candidate() -> None:
    event_id, claim_id = uuid4(), uuid4()
    claims = [
        ClaimTimelineInput(
            claim_id=claim_id,
            event_id=event_id,
            text="Claim",
            state="unresolved",
            evidence_signal_ids=[],
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
        TimelineReconstructionRunner._validate(payload, claims, [candidate])


def test_private_provenance_is_rejected_before_model_input() -> None:
    class StoredSignal:
        id = uuid4()
        title = "Private"
        normalized_text = "Sanitized"
        published_at = None
        source_type = "telegram"
        evidence_visibility = "private_sanitized"
        public_provenance = {"username": "forbidden"}

    with pytest.raises(IntelligenceError, match="INTELLIGENCE_PRIVATE_PROVENANCE_INVALID"):
        IntelligenceRepository._analysis_signal(StoredSignal())  # type: ignore[arg-type]
