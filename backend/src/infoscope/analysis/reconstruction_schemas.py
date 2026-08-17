from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from infoscope.analysis.schemas import StrictModel, TokenUsage
from infoscope.schemas.now import EventState

RECONSTRUCTION_SCHEMA_VERSION = "event_reconstruction.v1"
RECONSTRUCTION_MODEL_SCHEMA_VERSION = "event_reconstruction_model.v2"


class ExistingEventCandidate(StrictModel):
    event_id: UUID
    title: str
    overview: str
    state: EventState
    display_time: datetime
    signal_ids: list[UUID]


class NewEventDecision(StrictModel):
    decision_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    signal_ids: list[UUID] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: EventState
    display_time: datetime
    rationale: str = Field(min_length=1, max_length=4000)


class ExistingEventUpdate(StrictModel):
    decision_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    existing_event_id: UUID
    signal_ids: list[UUID] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: EventState
    display_time: datetime
    rationale: str = Field(min_length=1, max_length=4000)


class NewEventModelDecision(StrictModel):
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: EventState
    display_time: datetime
    rationale: str = Field(min_length=1, max_length=4000)


class ExistingEventModelUpdate(NewEventModelDecision):
    existing_event_id: UUID


class EventReconstructionModelPayload(StrictModel):
    schema_version: Literal["event_reconstruction_model.v2"] = (
        RECONSTRUCTION_MODEL_SCHEMA_VERSION
    )
    new_events: dict[str, NewEventModelDecision]
    existing_event_updates: dict[str, ExistingEventModelUpdate]
    signal_assignments: dict[UUID, str]

    @field_validator("new_events", "existing_event_updates")
    @classmethod
    def decision_keys_are_valid(cls, values: dict[str, object]) -> dict[str, object]:
        if any(
            re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", key) is None
            for key in values
        ):
            raise ValueError("decision_key values must be stable lowercase keys")
        return values

    @model_validator(mode="after")
    def assignments_reference_unique_decisions(self) -> EventReconstructionModelPayload:
        if set(self.new_events) & set(self.existing_event_updates):
            raise ValueError("decision_key values must be unique")
        referenced = set(self.signal_assignments.values())
        existing_ids = [
            decision.existing_event_id
            for key, decision in self.existing_event_updates.items()
            if key in referenced
        ]
        if len(existing_ids) != len(set(existing_ids)):
            raise ValueError("an existing event cannot be updated more than once")
        return self

    def to_event_payload(self, signal_ids: list[UUID]) -> EventReconstructionPayload:
        grouped: dict[str, list[UUID]] = {}
        unassigned: list[UUID] = []
        declared_keys = {*self.new_events, *self.existing_event_updates}
        for signal_id in signal_ids:
            decision_key = self.signal_assignments.get(signal_id)
            if decision_key is None or decision_key not in declared_keys:
                unassigned.append(signal_id)
            else:
                grouped.setdefault(decision_key, []).append(signal_id)
        return EventReconstructionPayload(
            new_events=[
                NewEventDecision(
                    decision_key=decision_key,
                    **self.new_events[decision_key].model_dump(),
                    signal_ids=grouped[decision_key],
                )
                for decision_key in sorted(set(grouped) & set(self.new_events))
            ],
            existing_event_updates=[
                ExistingEventUpdate(
                    decision_key=decision_key,
                    **self.existing_event_updates[decision_key].model_dump(),
                    signal_ids=grouped[decision_key],
                )
                for decision_key in sorted(
                    set(grouped) & set(self.existing_event_updates)
                )
            ],
            unassigned_signal_ids=unassigned,
        )


class EventReconstructionPayload(StrictModel):
    schema_version: Literal["event_reconstruction.v1"] = RECONSTRUCTION_SCHEMA_VERSION
    new_events: list[NewEventDecision]
    existing_event_updates: list[ExistingEventUpdate]
    unassigned_signal_ids: list[UUID]

    @model_validator(mode="after")
    def unique_decisions_and_assignments(self) -> EventReconstructionPayload:
        decisions = [*self.new_events, *self.existing_event_updates]
        keys = [decision.decision_key for decision in decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("decision_key values must be unique")
        assigned = [signal_id for decision in decisions for signal_id in decision.signal_ids]
        if len(assigned) != len(set(assigned)):
            raise ValueError("a signal cannot appear in multiple decisions")
        if len(self.unassigned_signal_ids) != len(set(self.unassigned_signal_ids)):
            raise ValueError("unassigned_signal_ids contains duplicates")
        if set(assigned) & set(self.unassigned_signal_ids):
            raise ValueError("assigned and unassigned signals must be disjoint")
        existing_ids = [decision.existing_event_id for decision in self.existing_event_updates]
        if len(existing_ids) != len(set(existing_ids)):
            raise ValueError("an existing event cannot be updated more than once")
        return self


class EventAssignment(StrictModel):
    decision_key: str
    event_id: UUID
    decision_type: Literal["new", "update"]


class EventReconstructionArtifact(StrictModel):
    schema_version: Literal["event_reconstruction.v1"] = RECONSTRUCTION_SCHEMA_VERSION
    source_artifact_id: UUID
    model_output: EventReconstructionPayload
    assignments: list[EventAssignment]

    @model_validator(mode="after")
    def assignments_match_decisions(self) -> EventReconstructionArtifact:
        expected = {
            decision.decision_key: "new" for decision in self.model_output.new_events
        }
        expected.update(
            {
                decision.decision_key: "update"
                for decision in self.model_output.existing_event_updates
            }
        )
        actual = {
            assignment.decision_key: assignment.decision_type
            for assignment in self.assignments
        }
        if len(actual) != len(self.assignments) or actual != expected:
            raise ValueError("assignments must map every reconstruction decision exactly once")
        for decision in self.model_output.existing_event_updates:
            assignment = next(
                value for value in self.assignments if value.decision_key == decision.decision_key
            )
            if assignment.event_id != decision.existing_event_id:
                raise ValueError("update assignment must preserve existing_event_id")
        return self


class EventReconstructionResponse(StrictModel):
    payload: EventReconstructionPayload
    provider: str
    model: str
    token_usage: TokenUsage
