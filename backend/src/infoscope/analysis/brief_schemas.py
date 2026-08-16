from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from infoscope.analysis.intelligence_schemas import BaseAnalysisEntity
from infoscope.analysis.schemas import StrictModel, TokenUsage

INPUT_SCHEMA_VERSION = "brief_input.v1"
OUTPUT_SCHEMA_VERSION = "brief.v1"
MAX_INPUT_BYTES = 2_097_152
MAX_OUTPUT_BYTES = 1_048_576
MAX_EVENTS = 8
PRIORITY_ORDER = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def canonical_json(value: StrictModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: StrictModel) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_hash(value: StrictModel) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _bounded(value: str, maximum: int, field_name: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped.encode("utf-8")) > maximum:
        raise ValueError(f"{field_name} exceeds its UTF-8 byte limit")
    return stripped


class BriefBaseAnalysis(StrictModel):
    base_analysis_id: UUID
    summary: str = Field(min_length=1, max_length=8000)
    event_type: str = Field(min_length=1, max_length=64)
    importance: Literal["low", "medium", "high", "critical"]
    topics: list[str] = Field(max_length=12)
    entities: list[BaseAnalysisEntity] = Field(max_length=32)

    @field_validator("summary")
    @classmethod
    def summary_limit(cls, value: str) -> str:
        return _bounded(value, 32_000, "summary")

    @field_validator("event_type")
    @classmethod
    def event_type_limit(cls, value: str) -> str:
        return _bounded(value, 256, "event type")

    @field_validator("topics")
    @classmethod
    def topics_are_bounded(cls, values: list[str]) -> list[str]:
        normalized = [_bounded(value, 256, "topic") for value in values]
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("topics must be unique")
        return normalized

    @field_validator("entities")
    @classmethod
    def entities_are_bounded(cls, values: list[BaseAnalysisEntity]) -> list[BaseAnalysisEntity]:
        for value in values:
            _bounded(value.name, 2048, "entity name")
            _bounded(value.entity_type, 256, "entity type")
        return values


class BriefClaim(StrictModel):
    claim_id: UUID
    text: str = Field(min_length=1, max_length=8000)
    state: Literal["confirmed", "unresolved", "conflicting", "contradicted"]

    @field_validator("text")
    @classmethod
    def text_limit(cls, value: str) -> str:
        return _bounded(value, 32_000, "claim text")


class BriefTimelineEntry(StrictModel):
    timeline_entry_id: UUID
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=8000)
    claim_ids: list[UUID] = Field(max_length=100)

    @field_validator("summary")
    @classmethod
    def summary_limit(cls, value: str) -> str:
        return _bounded(value, 32_000, "timeline summary")

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Brief Timeline time must be timezone-aware")
        return value


class BriefConflict(StrictModel):
    conflict_id: UUID
    summary: str = Field(min_length=1, max_length=8000)
    claim_ids: list[UUID] = Field(max_length=100)

    @field_validator("summary")
    @classmethod
    def summary_limit(cls, value: str) -> str:
        return _bounded(value, 32_000, "conflict summary")


class BriefPersonalization(StrictModel):
    priority: Literal["critical", "high", "normal", "low"]
    why_it_matters: str = Field(min_length=1, max_length=1200)
    personalized_angle: str = Field(min_length=1, max_length=1200)

    @field_validator("why_it_matters", "personalized_angle")
    @classmethod
    def text_limit(cls, value: str) -> str:
        return _bounded(value, 4800, "personalization text")


class BriefEventInput(StrictModel):
    event_id: UUID
    source_personalized_event_id: UUID
    personalization: BriefPersonalization
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: Literal["developing", "confirmed", "conflicting", "cooling"]
    display_time: datetime
    updated_at: datetime
    base_analysis: BriefBaseAnalysis
    claims: list[BriefClaim] = Field(max_length=100)
    timeline: list[BriefTimelineEntry] = Field(max_length=100)
    conflicts: list[BriefConflict] = Field(max_length=50)

    @field_validator("title")
    @classmethod
    def title_limit(cls, value: str) -> str:
        return _bounded(value, 2048, "title")

    @field_validator("overview")
    @classmethod
    def overview_limit(cls, value: str) -> str:
        return _bounded(value, 32_000, "overview")

    @field_validator("display_time", "updated_at")
    @classmethod
    def times_are_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Brief Event times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def relations_are_scoped_and_ordered(self) -> BriefEventInput:
        claim_ids = [item.claim_id for item in self.claims]
        timeline_ids = [item.timeline_entry_id for item in self.timeline]
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if any(
            len(values) != len(set(values)) for values in (claim_ids, timeline_ids, conflict_ids)
        ):
            raise ValueError("Brief facts must be unique")
        claim_set = set(claim_ids)
        claim_order = {item: index for index, item in enumerate(claim_ids)}
        for relation in [*self.timeline, *self.conflicts]:
            if len(relation.claim_ids) != len(set(relation.claim_ids)):
                raise ValueError("Brief relation claim IDs must be unique")
            if not set(relation.claim_ids) <= claim_set:
                raise ValueError("Brief relation contains an out-of-scope Claim")
            if relation.claim_ids != sorted(relation.claim_ids, key=claim_order.__getitem__):
                raise ValueError("Brief relation Claim IDs must preserve Backend order")
        return self


class BriefInput(StrictModel):
    schema_version: Literal["brief_input.v1"] = INPUT_SCHEMA_VERSION
    user_id: UUID
    source_personalization_artifact_id: UUID
    events: list[BriefEventInput] = Field(max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def events_are_unique(self) -> BriefInput:
        event_ids = [item.event_id for item in self.events]
        sources = [item.source_personalized_event_id for item in self.events]
        if len(event_ids) != len(set(event_ids)) or len(sources) != len(set(sources)):
            raise ValueError("Brief Events must be unique")
        expected = sorted(
            self.events,
            key=lambda item: (
                PRIORITY_ORDER[item.personalization.priority],
                -item.display_time.timestamp(),
                item.event_id,
            ),
        )
        if self.events != expected:
            raise ValueError("Brief Events must preserve Backend selection order")
        return self


class BriefDecision(StrictModel):
    event_id: UUID
    summary: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=1000)

    @field_validator("summary")
    @classmethod
    def summary_limit(cls, value: str) -> str:
        return _bounded(value, 8000, "Brief summary")

    @field_validator("rationale")
    @classmethod
    def rationale_limit(cls, value: str) -> str:
        return _bounded(value, 4000, "Brief rationale")


class BriefPayload(StrictModel):
    schema_version: Literal["brief.v1"] = OUTPUT_SCHEMA_VERSION
    items: list[BriefDecision] = Field(max_length=MAX_EVENTS)


class BriefResponse(StrictModel):
    payload: BriefPayload
    provider: str
    model: str
    token_usage: TokenUsage
