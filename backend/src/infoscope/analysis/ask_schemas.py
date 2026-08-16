from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from infoscope.analysis.intelligence_schemas import BaseAnalysisContent
from infoscope.analysis.schemas import StrictModel, TokenUsage
from infoscope.integrations.research.schemas import ResearchEvent


class AskRequestSpec(StrictModel):
    user_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    selected_event_ids: list[UUID] = Field(min_length=1, max_length=8)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized

    @field_validator("selected_event_ids")
    @classmethod
    def selected_events_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("selected_event_ids must be unique")
        return values


class AskBaseAnalysisInput(BaseAnalysisContent):
    base_analysis_id: UUID


class AskEventInput(ResearchEvent):
    base_analysis: AskBaseAnalysisInput


class AskComparisonInput(StrictModel):
    schema_version: Literal["ask_database_comparison_input.v1"] = (
        "ask_database_comparison_input.v1"
    )
    ask_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    selected_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    events: list[AskEventInput] = Field(min_length=1, max_length=8)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized

    @field_validator("selected_event_ids")
    @classmethod
    def selected_events_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("selected_event_ids must be unique")
        return values

    @model_validator(mode="after")
    def events_match_selection_order(self) -> AskComparisonInput:
        if [item.event_id for item in self.events] != self.selected_event_ids:
            raise ValueError("events must exactly match selected_event_ids order")
        return self


class AskMissingFact(StrictModel):
    event_ids: list[UUID] = Field(min_length=1, max_length=8)
    question: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("event_ids")
    @classmethod
    def event_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("missing fact event_ids must be unique")
        return values

    @field_validator("question", "reason")
    @classmethod
    def text_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("missing fact text must not be blank")
        return normalized


class AskComparisonPayload(StrictModel):
    schema_version: Literal["ask_database_comparison.v1"] = "ask_database_comparison.v1"
    ask_id: UUID
    decision: Literal["answerable", "research_required"]
    answer: str | None = Field(default=None, max_length=20_000)
    event_ids: list[UUID] = Field(min_length=1, max_length=8)
    claim_ids: list[UUID]
    timeline_entry_ids: list[UUID]
    conflict_ids: list[UUID]
    evidence_signal_ids: list[UUID]
    missing_facts: list[AskMissingFact] = Field(max_length=8)
    rationale: str = Field(min_length=1, max_length=4000)

    @field_validator(
        "event_ids",
        "claim_ids",
        "timeline_entry_ids",
        "conflict_ids",
        "evidence_signal_ids",
    )
    @classmethod
    def ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("output ID arrays must be unique")
        return values

    @field_validator("answer")
    @classmethod
    def answer_is_trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("rationale")
    @classmethod
    def rationale_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("rationale must not be blank")
        return normalized

    @model_validator(mode="after")
    def decision_is_consistent(self) -> AskComparisonPayload:
        if self.decision == "answerable":
            if self.answer is None or self.missing_facts:
                raise ValueError("answerable requires answer and no missing facts")
        elif self.answer is not None or not self.missing_facts:
            raise ValueError("research_required requires missing facts and no answer")
        keys = [(tuple(item.event_ids), item.question) for item in self.missing_facts]
        if len(keys) != len(set(keys)):
            raise ValueError("missing facts must be unique by event_ids and question")
        return self


class AskComparisonResponse(StrictModel):
    payload: AskComparisonPayload
    provider: str
    model: str
    token_usage: TokenUsage


def ask_input_hash(value: AskComparisonInput) -> str:
    document = {
        "question": value.question,
        "selected_event_ids": [str(item) for item in value.selected_event_ids],
        "events": [item.model_dump(mode="json") for item in value.events],
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
