from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from infoscope.analysis.intelligence_schemas import BaseAnalysisContent
from infoscope.analysis.schemas import StrictModel, TokenUsage
from infoscope.integrations.research.schemas import PublicSafeProvenance, ResearchEvent

_FULL_UUID_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
)
_LABELED_INTERNAL_ID_PATTERN = re.compile(
    r"(?i)\b(?:claim|timeline(?:\s+entry)?|conflict|signal|evidence|artifact|run|prompt)"
    r"(?:[\s_-]*id)?\s*[:#=()（）-]*\s*[0-9a-f]{8,32}\b"
)
_HEX_FRAGMENT_PATTERN = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{8,32}(?![0-9a-f])")


def validate_public_answer_syntax(value: str) -> str:
    """Reject internal identifier notation from model-authored public answer text."""
    if _FULL_UUID_PATTERN.search(value) or _LABELED_INTERNAL_ID_PATTERN.search(value):
        raise ValueError("public answer must not contain internal identifiers")
    return value


def public_answer_references_internal_uuid(answer: str, source: Any) -> bool:
    """Match UUID fragments in an answer only against IDs present in the frozen model input."""

    known: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, UUID):
            known.add(value.hex)
        elif isinstance(value, BaseModel):
            collect(value.model_dump())
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                collect(item)

    collect(source)
    return any(
        any(fragment.lower() in identifier for identifier in known)
        for fragment in _HEX_FRAGMENT_PATTERN.findall(answer)
    )


class AskRequestSpec(StrictModel):
    user_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    selected_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    grok_enabled: bool = False

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
    schema_version: Literal["ask_database_comparison_input.v1"] = "ask_database_comparison_input.v1"
    ask_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    selected_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    grok_enabled: bool = False
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
        return validate_public_answer_syntax(normalized) if normalized else None

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


class AskResearchResult(StrictModel):
    candidate_index: int = Field(ge=0, le=11)
    research_source_id: UUID
    raw_information_id: UUID
    signal_ids: list[UUID] = Field(min_length=1)

    @field_validator("signal_ids")
    @classmethod
    def signals_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("bridge result signal_ids must be unique")
        return values


class AskResearchArtifactPayload(StrictModel):
    schema_version: Literal["ask_research_bridge.v1"] = "ask_research_bridge.v1"
    ask_id: UUID
    comparison_artifact_id: UUID
    research_request_id: UUID
    source_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    research_status: Literal["succeeded", "partial"]
    results: list[AskResearchResult] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def relations_are_unique(self) -> AskResearchArtifactPayload:
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("source_event_ids must be unique")
        indexes = [item.candidate_index for item in self.results]
        source_ids = [item.research_source_id for item in self.results]
        raw_ids = [item.raw_information_id for item in self.results]
        if len(indexes) != len(set(indexes)):
            raise ValueError("candidate indexes must be unique")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("research source ids must be unique")
        if len(raw_ids) != len(set(raw_ids)):
            raise ValueError("raw information ids must be unique")
        return self


def ask_input_hash(value: AskComparisonInput) -> str:
    document = {
        "question": value.question,
        "selected_event_ids": [str(item) for item in value.selected_event_ids],
        "grok_enabled": value.grok_enabled,
        "events": [item.model_dump(mode="json") for item in value.events],
    }
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class AskReconciliationMissingFact(StrictModel):
    event_ids: list[UUID] = Field(min_length=1, max_length=8)
    question: str = Field(min_length=1, max_length=500)

    @field_validator("event_ids")
    @classmethod
    def event_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("reconciliation missing fact event_ids must be unique")
        return values

    @field_validator("question")
    @classmethod
    def question_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reconciliation missing fact question must not be blank")
        return normalized


class AskReconciliationSignal(StrictModel):
    canonical_signal_id: UUID
    observation_signal_ids: list[UUID] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=512)
    sanitized_text: str = Field(min_length=1, max_length=20_000)
    published_at: datetime | None
    evidence_visibility: Literal["public", "private_sanitized"]
    public_safe_provenance: PublicSafeProvenance | None

    @field_validator("observation_signal_ids")
    @classmethod
    def observations_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("observation_signal_ids must be unique")
        return values

    @field_validator("published_at")
    @classmethod
    def published_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("published_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def private_has_no_provenance(self) -> AskReconciliationSignal:
        if (
            self.evidence_visibility == "private_sanitized"
            and self.public_safe_provenance is not None
        ):
            raise ValueError("private reconciliation evidence cannot include provenance")
        return self


class AskEventReconciliationInput(StrictModel):
    schema_version: Literal["ask_event_reconciliation_input.v1"] = (
        "ask_event_reconciliation_input.v1"
    )
    ask_id: UUID
    source_bridge_artifact_id: UUID
    source_bridge_payload: AskResearchArtifactPayload
    question: str = Field(min_length=1, max_length=2000)
    missing_facts: list[AskReconciliationMissingFact] = Field(min_length=1, max_length=8)
    source_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    events: list[AskEventInput] = Field(min_length=1, max_length=8)
    canonical_signals: list[AskReconciliationSignal] = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def question_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reconciliation question must not be blank")
        return normalized

    @field_validator("source_event_ids")
    @classmethod
    def source_events_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("source_event_ids must be unique")
        return values

    @model_validator(mode="after")
    def relations_are_complete(self) -> AskEventReconciliationInput:
        if self.source_bridge_payload.ask_id != self.ask_id:
            raise ValueError("source bridge payload must belong to the Ask")
        if self.source_bridge_payload.source_event_ids != self.source_event_ids:
            raise ValueError("source events must match the bridge order")
        if [item.event_id for item in self.events] != self.source_event_ids:
            raise ValueError("events must exactly match source_event_ids order")
        selected = set(self.source_event_ids)
        if any(not set(item.event_ids) <= selected for item in self.missing_facts):
            raise ValueError("missing facts must stay within source events")
        canonical_ids = [item.canonical_signal_id for item in self.canonical_signals]
        observations = [
            signal_id
            for item in self.canonical_signals
            for signal_id in item.observation_signal_ids
        ]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ValueError("canonical signals must be unique")
        if len(observations) != len(set(observations)):
            raise ValueError("observations must map to exactly one canonical Signal")
        bridge_observations = [
            signal_id
            for result in self.source_bridge_payload.results
            for signal_id in result.signal_ids
        ]
        if set(observations) != set(bridge_observations):
            raise ValueError("canonical mappings must cover every bridge observation")
        observation_to_canonical = {
            observation_id: item.canonical_signal_id
            for item in self.canonical_signals
            for observation_id in item.observation_signal_ids
        }
        expected_order = list(
            dict.fromkeys(observation_to_canonical[item] for item in bridge_observations)
        )
        if canonical_ids != expected_order:
            raise ValueError("canonical Signal order must follow first bridge appearance")
        return self


class AskEventUpdate(StrictModel):
    event_id: UUID
    signal_ids: list[UUID] = Field(min_length=1)
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    display_time: datetime
    rationale: str = Field(min_length=1, max_length=4000)

    @field_validator("signal_ids")
    @classmethod
    def signals_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("event update signal_ids must be unique")
        return values

    @field_validator("title", "overview", "rationale")
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


class AskEventReconciliationPayload(StrictModel):
    schema_version: Literal["ask_event_reconciliation.v1"] = "ask_event_reconciliation.v1"
    ask_id: UUID
    event_updates: list[AskEventUpdate] = Field(max_length=8)
    unassigned_signal_ids: list[UUID]

    @field_validator("unassigned_signal_ids")
    @classmethod
    def unassigned_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("unassigned_signal_ids must be unique")
        return values

    @model_validator(mode="after")
    def updates_are_unique(self) -> AskEventReconciliationPayload:
        event_ids = [item.event_id for item in self.event_updates]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("an Event may be updated at most once")
        assigned = {signal_id for item in self.event_updates for signal_id in item.signal_ids}
        if assigned & set(self.unassigned_signal_ids):
            raise ValueError("assigned Signals cannot also be unassigned")
        return self


class AskEventReconciliationResponse(StrictModel):
    payload: AskEventReconciliationPayload
    provider: str
    model: str
    token_usage: TokenUsage


class AskEventReconciliationAssignment(StrictModel):
    event_id: UUID
    signal_ids: list[UUID] = Field(min_length=1)
    newly_attached_signal_ids: list[UUID]

    @model_validator(mode="after")
    def attachment_ids_are_consistent(self) -> AskEventReconciliationAssignment:
        if len(self.signal_ids) != len(set(self.signal_ids)) or len(
            self.newly_attached_signal_ids
        ) != len(set(self.newly_attached_signal_ids)):
            raise ValueError("assignment Signal IDs must be unique")
        if not set(self.newly_attached_signal_ids) <= set(self.signal_ids):
            raise ValueError("newly attached Signals must belong to the assignment")
        return self


class AskEventReconciliationArtifactPayload(StrictModel):
    schema_version: Literal["ask_event_reconciliation.v1"] = "ask_event_reconciliation.v1"
    ask_id: UUID
    source_bridge_artifact_id: UUID
    output: AskEventReconciliationPayload
    assignments: list[AskEventReconciliationAssignment] = Field(min_length=1, max_length=8)
    updated_event_ids: list[UUID] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def assignments_match_output(self) -> AskEventReconciliationArtifactPayload:
        if self.output.ask_id != self.ask_id:
            raise ValueError("artifact output must belong to the Ask")
        assignment_ids = [item.event_id for item in self.assignments]
        if assignment_ids != self.updated_event_ids or len(assignment_ids) != len(
            set(assignment_ids)
        ):
            raise ValueError("assignments must match ordered updated_event_ids")
        output_by_event = {item.event_id: item.signal_ids for item in self.output.event_updates}
        if set(output_by_event) != set(assignment_ids) or any(
            output_by_event[item.event_id] != item.signal_ids for item in self.assignments
        ):
            raise ValueError("assignments must exactly match model output")
        return self


def ask_reconciliation_input_hash(value: AskEventReconciliationInput) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class AskFinalizationInput(StrictModel):
    schema_version: Literal["ask_finalization_input.v1"] = "ask_finalization_input.v1"
    ask_id: UUID
    source_comparison_artifact_id: UUID
    source_reconciliation_artifact_id: UUID
    source_comparison_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_reconciliation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    question: str = Field(min_length=1, max_length=2000)
    selected_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    updated_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    events: list[AskEventInput] = Field(min_length=1, max_length=8)

    @field_validator("question")
    @classmethod
    def finalization_question_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("finalization question must not be blank")
        return normalized

    @field_validator("selected_event_ids", "updated_event_ids")
    @classmethod
    def finalization_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("finalization Event IDs must be unique")
        return values

    @model_validator(mode="after")
    def finalization_relations_are_valid(self) -> AskFinalizationInput:
        if [item.event_id for item in self.events] != self.selected_event_ids:
            raise ValueError("events must exactly match selected_event_ids order")
        if not set(self.updated_event_ids) <= set(self.selected_event_ids):
            raise ValueError("updated_event_ids must stay within selected Events")
        return self


class AskFinalAnswerPayload(StrictModel):
    schema_version: Literal["ask_final_answer.v1"] = "ask_final_answer.v1"
    ask_id: UUID
    answer: str = Field(min_length=1, max_length=20_000)
    event_ids: list[UUID] = Field(min_length=1, max_length=8)
    claim_ids: list[UUID]
    timeline_entry_ids: list[UUID]
    conflict_ids: list[UUID]
    evidence_signal_ids: list[UUID]
    updated_event_ids: list[UUID]

    @field_validator("answer")
    @classmethod
    def final_answer_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("final answer must not be blank")
        return normalized

    @field_validator(
        "event_ids",
        "claim_ids",
        "timeline_entry_ids",
        "conflict_ids",
        "evidence_signal_ids",
        "updated_event_ids",
    )
    @classmethod
    def final_answer_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("final answer ID arrays must be unique")
        return values


class AskFinalizationModelPayload(StrictModel):
    schema_version: Literal["ask_finalization.v1"] = "ask_finalization.v1"
    ask_id: UUID
    answer: str = Field(min_length=1, max_length=20_000)
    event_ids: list[UUID] = Field(min_length=1, max_length=8)
    claim_ids: list[UUID]
    timeline_entry_ids: list[UUID]
    conflict_ids: list[UUID]
    evidence_signal_ids: list[UUID]

    @field_validator("answer")
    @classmethod
    def model_answer_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("model answer must not be blank")
        return validate_public_answer_syntax(normalized)

    @field_validator(
        "event_ids", "claim_ids", "timeline_entry_ids", "conflict_ids", "evidence_signal_ids"
    )
    @classmethod
    def model_answer_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("model answer ID arrays must be unique")
        return values


class AskFinalizationResponse(StrictModel):
    payload: AskFinalizationModelPayload
    provider: str
    model: str
    token_usage: TokenUsage


def ask_finalization_input_hash(value: AskFinalizationInput) -> str:
    encoded = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
