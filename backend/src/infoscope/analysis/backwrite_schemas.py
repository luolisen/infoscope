from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from infoscope.analysis.ask_schemas import AskEventInput, AskReconciliationSignal
from infoscope.analysis.intelligence_schemas import (
    BaseAnalysisResponse,
    ClaimExtractionResponse,
    ConflictAnalysisResponse,
    TimelineReconstructionResponse,
)
from infoscope.analysis.schemas import StrictModel, TokenUsage


class BackwriteSnapshotSpec(StrictModel):
    user_id: UUID
    idempotency_key: UUID


class BackwriteSnapshotPayload(StrictModel):
    schema_version: Literal["backwrite_snapshot.v1"] = "backwrite_snapshot.v1"
    user_id: UUID
    ordered_event_ids: list[UUID]

    @field_validator("ordered_event_ids")
    @classmethod
    def event_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("ordered_event_ids must be unique")
        return values


class BackwriteReconciliationInput(StrictModel):
    schema_version: Literal["backwrite_reconciliation_input.v1"] = (
        "backwrite_reconciliation_input.v1"
    )
    item_id: UUID
    event_id: UUID
    event: AskEventInput
    canonical_signals: list[AskReconciliationSignal]

    @model_validator(mode="after")
    def relations_are_valid(self) -> BackwriteReconciliationInput:
        if self.event.event_id != self.event_id:
            raise ValueError("event must match event_id")
        canonical_ids = [item.canonical_signal_id for item in self.canonical_signals]
        observations = [
            signal_id
            for item in self.canonical_signals
            for signal_id in item.observation_signal_ids
        ]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ValueError("canonical Signals must be unique")
        if len(observations) != len(set(observations)):
            raise ValueError("observations must map to exactly one canonical Signal")
        return self


class BackwriteResearchResult(StrictModel):
    candidate_index: int = Field(ge=0, le=11)
    research_source_id: UUID
    raw_information_id: UUID
    observation_signal_ids: list[UUID]

    @field_validator("observation_signal_ids")
    @classmethod
    def observation_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("observation Signal IDs must be unique")
        return values


class BackwriteResearchArtifactPayload(StrictModel):
    schema_version: Literal["backwrite_research.v1"] = "backwrite_research.v1"
    item_id: UUID
    event_id: UUID
    research_request_id: UUID
    research_status: Literal["succeeded", "partial"]
    results: list[BackwriteResearchResult] = Field(max_length=12)

    @model_validator(mode="after")
    def result_relations_are_unique(self) -> BackwriteResearchArtifactPayload:
        indexes = [item.candidate_index for item in self.results]
        source_ids = [item.research_source_id for item in self.results]
        raw_ids = [item.raw_information_id for item in self.results]
        observation_ids = [
            signal_id for item in self.results for signal_id in item.observation_signal_ids
        ]
        if len(indexes) != len(set(indexes)):
            raise ValueError("candidate indexes must be unique")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Research source IDs must be unique")
        if len(raw_ids) != len(set(raw_ids)):
            raise ValueError("Raw Information IDs must be unique")
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation Signals must belong to exactly one result")
        return self


class BackwriteEventUpdate(StrictModel):
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    display_time: datetime
    signal_ids: list[UUID] = Field(min_length=1)

    @field_validator("title", "overview")
    @classmethod
    def text_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event update text must not be blank")
        return normalized

    @field_validator("display_time")
    @classmethod
    def display_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("display_time must be timezone-aware")
        return value

    @field_validator("signal_ids")
    @classmethod
    def signal_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("event update signal_ids must be unique")
        return values


class BackwriteReconciliationPayload(StrictModel):
    schema_version: Literal["backwrite_reconciliation.v1"] = "backwrite_reconciliation.v1"
    item_id: UUID
    event_id: UUID
    decision: Literal["update", "no_change"]
    event_update: BackwriteEventUpdate | None
    unassigned_signal_ids: list[UUID]
    rationale: str = Field(min_length=1, max_length=4000)

    @field_validator("unassigned_signal_ids")
    @classmethod
    def unassigned_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("unassigned_signal_ids must be unique")
        return values

    @field_validator("rationale")
    @classmethod
    def rationale_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("rationale must not be blank")
        return normalized

    @model_validator(mode="after")
    def decision_matches_update(self) -> BackwriteReconciliationPayload:
        if self.decision == "update" and self.event_update is None:
            raise ValueError("update requires event_update")
        if self.decision == "no_change" and self.event_update is not None:
            raise ValueError("no_change cannot include event_update")
        assigned = set(self.event_update.signal_ids) if self.event_update is not None else set()
        if assigned & set(self.unassigned_signal_ids):
            raise ValueError("assigned Signals cannot also be unassigned")
        return self


class BackwriteReconciliationResponse(StrictModel):
    payload: BackwriteReconciliationPayload
    provider: str
    model: str
    token_usage: TokenUsage


class BackwriteDownstreamRefresh(StrictModel):
    claims: ClaimExtractionResponse
    timeline: TimelineReconstructionResponse
    conflicts: ConflictAnalysisResponse
    base_analysis: BaseAnalysisResponse


class BackwriteReconciliationArtifactPayload(StrictModel):
    schema_version: Literal["backwrite_reconciliation.v1"] = "backwrite_reconciliation.v1"
    item_id: UUID
    event_id: UUID
    research_request_id: UUID
    output: BackwriteReconciliationPayload
    newly_attached_signal_ids: list[UUID]
    downstream_refresh: BackwriteDownstreamRefresh | None

    @model_validator(mode="after")
    def output_matches_item(self) -> BackwriteReconciliationArtifactPayload:
        if self.output.item_id != self.item_id or self.output.event_id != self.event_id:
            raise ValueError("artifact output must match item and Event")
        if len(self.newly_attached_signal_ids) != len(set(self.newly_attached_signal_ids)):
            raise ValueError("newly attached Signals must be unique")
        assigned = (
            set(self.output.event_update.signal_ids)
            if self.output.event_update is not None
            else set()
        )
        if not set(self.newly_attached_signal_ids) <= assigned:
            raise ValueError("new attachments must belong to the output assignment")
        if self.output.decision == "update" and self.downstream_refresh is None:
            raise ValueError("updated Event artifact requires complete downstream refresh")
        if self.output.decision == "no_change" and self.downstream_refresh is not None:
            raise ValueError("no-change artifact cannot contain downstream refresh")
        return self


def backwrite_snapshot_hash(value: BackwriteSnapshotPayload) -> str:
    return _hash(value.model_dump(mode="json"))


def backwrite_reconciliation_input_hash(value: BackwriteReconciliationInput) -> str:
    return _hash(value.model_dump(mode="json"))


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
