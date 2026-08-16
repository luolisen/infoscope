from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from infoscope.analysis.schemas import AnalysisSignal, StrictModel, TokenUsage


class EventClaimInput(StrictModel):
    event_id: UUID
    title: str
    overview: str
    signals: list[AnalysisSignal]


class ExistingClaimCandidate(StrictModel):
    claim_id: UUID
    event_id: UUID
    text: str
    state: Literal["confirmed", "unresolved", "conflicting", "contradicted"]
    evidence_signal_ids: list[UUID]


class NewClaimDecision(StrictModel):
    decision_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    event_id: UUID
    text: str = Field(min_length=1, max_length=8000)
    evidence_signal_ids: list[UUID] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=4000)


class ExistingClaimUpdate(NewClaimDecision):
    existing_claim_id: UUID


class ClaimExtractionPayload(StrictModel):
    schema_version: Literal["claim_extraction.v1"] = "claim_extraction.v1"
    new_claims: list[NewClaimDecision]
    existing_claim_updates: list[ExistingClaimUpdate]
    unused_signal_ids: list[UUID]

    @model_validator(mode="after")
    def validate_decisions(self) -> ClaimExtractionPayload:
        decisions = [*self.new_claims, *self.existing_claim_updates]
        if any(
            len(item.evidence_signal_ids) != len(set(item.evidence_signal_ids))
            for item in decisions
        ):
            raise ValueError("evidence_signal_ids contains duplicates")
        keys = [item.decision_key for item in decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("decision_key values must be unique")
        existing = [item.existing_claim_id for item in self.existing_claim_updates]
        if len(existing) != len(set(existing)):
            raise ValueError("an existing claim cannot be updated more than once")
        if len(self.unused_signal_ids) != len(set(self.unused_signal_ids)):
            raise ValueError("unused_signal_ids contains duplicates")
        used = {value for item in decisions for value in item.evidence_signal_ids}
        if used & set(self.unused_signal_ids):
            raise ValueError("used and unused signals must be disjoint")
        return self


class ClaimAssignment(StrictModel):
    decision_key: str
    event_id: UUID
    claim_id: UUID
    decision_type: Literal["new", "update"]


class ClaimExtractionArtifact(StrictModel):
    schema_version: Literal["claim_extraction.v1"] = "claim_extraction.v1"
    source_artifact_id: UUID
    model_output: ClaimExtractionPayload
    assignments: list[ClaimAssignment]

    @model_validator(mode="after")
    def assignments_match_decisions(self) -> ClaimExtractionArtifact:
        decisions = {
            item.decision_key: (item.event_id, "new") for item in self.model_output.new_claims
        }
        decisions.update(
            {
                item.decision_key: (item.event_id, "update")
                for item in self.model_output.existing_claim_updates
            }
        )
        actual = {
            item.decision_key: (item.event_id, item.decision_type) for item in self.assignments
        }
        if len(actual) != len(self.assignments) or actual != decisions:
            raise ValueError("assignments must map every claim decision exactly once")
        for decision in self.model_output.existing_claim_updates:
            assignment = next(
                item for item in self.assignments if item.decision_key == decision.decision_key
            )
            if assignment.claim_id != decision.existing_claim_id:
                raise ValueError("update assignment must preserve existing_claim_id")
        return self


class ClaimExtractionResponse(StrictModel):
    payload: ClaimExtractionPayload
    provider: str
    model: str
    token_usage: TokenUsage


class ClaimTimelineInput(StrictModel):
    claim_id: UUID
    event_id: UUID
    text: str
    state: str
    evidence_signal_ids: list[UUID]


class ExistingTimelineCandidate(StrictModel):
    timeline_entry_id: UUID
    event_id: UUID
    occurred_at: datetime
    summary: str
    claim_ids: list[UUID]


class NewTimelineDecision(StrictModel):
    decision_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    event_id: UUID
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=8000)
    claim_ids: list[UUID] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=4000)


class ExistingTimelineUpdate(NewTimelineDecision):
    existing_timeline_entry_id: UUID


class TimelineReconstructionPayload(StrictModel):
    schema_version: Literal["timeline_reconstruction.v1"] = "timeline_reconstruction.v1"
    new_entries: list[NewTimelineDecision]
    existing_entry_updates: list[ExistingTimelineUpdate]
    unused_claim_ids: list[UUID]

    @model_validator(mode="after")
    def validate_decisions(self) -> TimelineReconstructionPayload:
        decisions = [*self.new_entries, *self.existing_entry_updates]
        if any(len(item.claim_ids) != len(set(item.claim_ids)) for item in decisions):
            raise ValueError("claim_ids contains duplicates")
        keys = [item.decision_key for item in decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("decision_key values must be unique")
        existing = [item.existing_timeline_entry_id for item in self.existing_entry_updates]
        if len(existing) != len(set(existing)):
            raise ValueError("a timeline entry cannot be updated more than once")
        if len(self.unused_claim_ids) != len(set(self.unused_claim_ids)):
            raise ValueError("unused_claim_ids contains duplicates")
        used = {value for item in decisions for value in item.claim_ids}
        if used & set(self.unused_claim_ids):
            raise ValueError("used and unused claims must be disjoint")
        return self


class TimelineAssignment(StrictModel):
    decision_key: str
    event_id: UUID
    timeline_entry_id: UUID
    decision_type: Literal["new", "update"]


class TimelineReconstructionArtifact(StrictModel):
    schema_version: Literal["timeline_reconstruction.v1"] = "timeline_reconstruction.v1"
    source_artifact_id: UUID
    model_output: TimelineReconstructionPayload
    assignments: list[TimelineAssignment]

    @model_validator(mode="after")
    def assignments_match_decisions(self) -> TimelineReconstructionArtifact:
        decisions = {
            item.decision_key: (item.event_id, "new") for item in self.model_output.new_entries
        }
        decisions.update(
            {
                item.decision_key: (item.event_id, "update")
                for item in self.model_output.existing_entry_updates
            }
        )
        actual = {
            item.decision_key: (item.event_id, item.decision_type) for item in self.assignments
        }
        if len(actual) != len(self.assignments) or actual != decisions:
            raise ValueError("assignments must map every timeline decision exactly once")
        for decision in self.model_output.existing_entry_updates:
            assignment = next(
                item for item in self.assignments if item.decision_key == decision.decision_key
            )
            if assignment.timeline_entry_id != decision.existing_timeline_entry_id:
                raise ValueError("update assignment must preserve existing_timeline_entry_id")
        return self


class TimelineReconstructionResponse(StrictModel):
    payload: TimelineReconstructionPayload
    provider: str
    model: str
    token_usage: TokenUsage
