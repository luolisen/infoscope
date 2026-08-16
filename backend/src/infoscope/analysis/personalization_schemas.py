from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from infoscope.analysis.intelligence_schemas import BaseAnalysisEntity
from infoscope.analysis.schemas import StrictModel, TokenUsage
from infoscope.schemas.onboarding import FocusId, InvestmentMarketId, ScopeId

INPUT_SCHEMA_VERSION = "personalization_input.v1"
OUTPUT_SCHEMA_VERSION = "personalization.v1"
MAX_CANONICAL_BYTES = 4_194_304
MAX_EVENTS = 100


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


def _bounded(value: str, *, maximum: int, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized.encode("utf-8")) > maximum:
        raise ValueError(f"{field_name} exceeds its UTF-8 byte limit")
    return normalized


class PersonalizationProfile(StrictModel):
    scope_ids: list[ScopeId] = Field(min_length=1, max_length=5)
    investment_market_ids: list[InvestmentMarketId] = Field(max_length=3)
    focus_ids: list[FocusId] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def selections_are_valid(self) -> PersonalizationProfile:
        for values in (self.scope_ids, self.investment_market_ids, self.focus_ids):
            if len(values) != len(set(values)):
                raise ValueError("profile selections must be unique")
        investment = ScopeId.INVESTMENT in self.scope_ids
        if investment != bool(self.investment_market_ids):
            raise ValueError("investment markets must match the investment scope")
        return self


class PersonalizationBaseAnalysis(StrictModel):
    base_analysis_id: UUID
    summary: str = Field(min_length=1, max_length=8000)
    event_type: str = Field(min_length=1, max_length=64)
    importance: Literal["low", "medium", "high", "critical"]
    topics: list[str] = Field(max_length=12)
    entities: list[BaseAnalysisEntity] = Field(max_length=32)

    @field_validator("summary")
    @classmethod
    def summary_bytes(cls, value: str) -> str:
        return _bounded(value, maximum=32_000, field_name="summary")

    @field_validator("event_type")
    @classmethod
    def event_type_bytes(cls, value: str) -> str:
        return _bounded(value, maximum=256, field_name="event_type")

    @field_validator("topics")
    @classmethod
    def topics_are_bounded(cls, values: list[str]) -> list[str]:
        normalized = [_bounded(value, maximum=256, field_name="topic") for value in values]
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("topics must be unique")
        return normalized

    @field_validator("entities")
    @classmethod
    def entities_are_bounded(cls, values: list[BaseAnalysisEntity]) -> list[BaseAnalysisEntity]:
        for value in values:
            _bounded(value.name, maximum=2048, field_name="entity name")
            _bounded(value.entity_type, maximum=256, field_name="entity type")
        return values


class PersonalizationEventInput(StrictModel):
    event_id: UUID
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: Literal["developing", "confirmed", "conflicting", "cooling"]
    display_time: datetime
    updated_at: datetime
    base_analysis: PersonalizationBaseAnalysis

    @field_validator("title")
    @classmethod
    def title_bytes(cls, value: str) -> str:
        return _bounded(value, maximum=2048, field_name="title")

    @field_validator("overview")
    @classmethod
    def overview_bytes(cls, value: str) -> str:
        return _bounded(value, maximum=32_000, field_name="overview")


class PersonalizationInput(StrictModel):
    schema_version: Literal["personalization_input.v1"] = INPUT_SCHEMA_VERSION
    user_id: UUID
    profile: PersonalizationProfile
    events: list[PersonalizationEventInput] = Field(max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def events_are_unique_and_ordered(self) -> PersonalizationInput:
        ids = [item.event_id for item in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("events must be unique")
        expected = sorted(
            self.events, key=lambda item: (-item.display_time.timestamp(), item.event_id)
        )
        if self.events != expected:
            raise ValueError("events must use Backend display order")
        return self


class PersonalizationDecision(StrictModel):
    event_id: UUID
    relevant: bool
    priority: Literal["critical", "high", "normal", "low"]
    why_it_matters: str | None
    personalized_angle: str | None
    matched_scope_ids: list[ScopeId] = Field(max_length=5)
    matched_focus_ids: list[FocusId] = Field(max_length=8)
    rationale: str = Field(min_length=1, max_length=2000)

    @field_validator("why_it_matters", "personalized_angle")
    @classmethod
    def public_text_bytes(cls, value: str | None) -> str | None:
        return None if value is None else _bounded(value, maximum=4800, field_name="public text")

    @field_validator("rationale")
    @classmethod
    def rationale_bytes(cls, value: str) -> str:
        return _bounded(value, maximum=8000, field_name="rationale")

    @model_validator(mode="after")
    def relevance_fields_match(self) -> PersonalizationDecision:
        arrays = (self.matched_scope_ids, self.matched_focus_ids)
        if any(len(values) != len(set(values)) for values in arrays):
            raise ValueError("matched profile ids must be unique")
        if self.relevant:
            if self.why_it_matters is None or self.personalized_angle is None:
                raise ValueError("relevant decisions require public text")
            if not self.matched_scope_ids or not self.matched_focus_ids:
                raise ValueError("relevant decisions require matched profile ids")
        elif any(
            (
                self.why_it_matters is not None,
                self.personalized_angle is not None,
                bool(self.matched_scope_ids),
                bool(self.matched_focus_ids),
            )
        ):
            raise ValueError("irrelevant decisions cannot contain public personalization")
        return self


class PersonalizationPayload(StrictModel):
    schema_version: Literal["personalization.v1"] = OUTPUT_SCHEMA_VERSION
    decisions: list[PersonalizationDecision] = Field(max_length=MAX_EVENTS)


class PersonalizationResponse(StrictModel):
    payload: PersonalizationPayload
    provider: str
    model: str
    token_usage: TokenUsage
