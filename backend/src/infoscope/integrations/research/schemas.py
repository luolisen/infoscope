from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator, model_validator

from infoscope.analysis.schemas import StrictModel
from infoscope.models import ResearchSourceKind, ResearchTrigger


class TrendRadarProvenance(StrictModel):
    kind: Literal["trend_radar"]
    source_kind: str = Field(min_length=1, max_length=64)
    source_name: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=2048)


class TelegramPublicProvenance(StrictModel):
    kind: Literal["telegram_public"]
    platform: Literal["telegram"]
    chat_title: str | None = Field(default=None, max_length=512)
    chat_username: str | None = Field(default=None, max_length=128)
    url: str | None = Field(default=None, max_length=2048)


class ResearchProvenance(StrictModel):
    kind: Literal["research"]
    source_kind: Literal["web_page", "github_document"]
    canonical_url: str = Field(min_length=1, max_length=2048)


PublicSafeProvenance = Annotated[
    TrendRadarProvenance | TelegramPublicProvenance | ResearchProvenance,
    Field(discriminator="kind"),
]
PROVENANCE_ADAPTER = TypeAdapter(PublicSafeProvenance)


class ResearchEvidence(StrictModel):
    signal_id: UUID
    published_at: datetime | None
    sanitized_text: str = Field(min_length=1, max_length=20_000)
    evidence_visibility: Literal["public", "private_sanitized"]
    public_safe_provenance: PublicSafeProvenance | None

    @model_validator(mode="after")
    def private_has_no_provenance(self) -> ResearchEvidence:
        if (
            self.evidence_visibility == "private_sanitized"
            and self.public_safe_provenance is not None
        ):
            raise ValueError("private evidence cannot include provenance")
        return self

    @field_validator("published_at")
    @classmethod
    def published_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("published_at must be timezone-aware")
        return value


class ResearchClaim(StrictModel):
    claim_id: UUID
    text: str = Field(min_length=1, max_length=8000)
    state: Literal["confirmed", "unresolved", "conflicting", "contradicted"]
    evidence_signal_ids: list[UUID]

    @field_validator("evidence_signal_ids")
    @classmethod
    def evidence_is_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("claim evidence ids must be unique")
        return values


class ResearchTimeline(StrictModel):
    timeline_entry_id: UUID
    occurred_at: datetime
    summary: str = Field(min_length=1, max_length=8000)
    claim_ids: list[UUID]

    @field_validator("claim_ids")
    @classmethod
    def claims_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("timeline claim ids must be unique")
        return values

    @field_validator("occurred_at")
    @classmethod
    def occurred_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class ResearchConflict(StrictModel):
    conflict_id: UUID
    summary: str = Field(min_length=1, max_length=8000)
    claim_ids: list[UUID]
    evidence_signal_ids: list[UUID]

    @field_validator("claim_ids", "evidence_signal_ids")
    @classmethod
    def ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("conflict relation ids must be unique")
        return values


class ResearchEvent(StrictModel):
    event_id: UUID
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: Literal["developing", "confirmed", "conflicting", "cooling"]
    display_time: datetime
    claims: list[ResearchClaim] = Field(max_length=128)
    timeline: list[ResearchTimeline] = Field(max_length=128)
    conflicts: list[ResearchConflict] = Field(max_length=64)
    evidence_signals: list[ResearchEvidence] = Field(max_length=256)

    @field_validator("display_time")
    @classmethod
    def display_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("display_time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def relationships_stay_in_event(self) -> ResearchEvent:
        claims = {item.claim_id: set(item.evidence_signal_ids) for item in self.claims}
        evidence = {item.signal_id for item in self.evidence_signals}
        if len(claims) != len(self.claims) or len(evidence) != len(self.evidence_signals):
            raise ValueError("event facts contain duplicate ids")
        if any(not signal_ids <= evidence for signal_ids in claims.values()):
            raise ValueError("claim evidence must belong to the event")
        timeline_ids = [item.timeline_entry_id for item in self.timeline]
        if len(timeline_ids) != len(set(timeline_ids)):
            raise ValueError("timeline ids must be unique")
        if any(not set(item.claim_ids) <= claims.keys() for item in self.timeline):
            raise ValueError("timeline claims must belong to the event")
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("conflict ids must be unique")
        for item in self.conflicts:
            if not set(item.claim_ids) <= claims.keys():
                raise ValueError("conflict claims must belong to the event")
            permitted = {signal_id for claim_id in item.claim_ids for signal_id in claims[claim_id]}
            if not set(item.evidence_signal_ids) <= permitted:
                raise ValueError("conflict evidence must be attached to its claims")
        return self


class ResearchFactSnapshot(StrictModel):
    schema_version: Literal["research_fact_snapshot.v1"] = "research_fact_snapshot.v1"
    events: list[ResearchEvent] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def events_are_unique(self) -> ResearchFactSnapshot:
        ids = [item.event_id for item in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot events must be unique")
        return self


class ResearchRequestSpec(StrictModel):
    idempotency_key: UUID
    trigger: ResearchTrigger
    source_event_ids: list[UUID] = Field(min_length=1, max_length=8)
    research_questions: list[str] = Field(min_length=1, max_length=8)
    missing_fact_descriptions: list[str] = Field(max_length=16)
    allowed_source_kinds: list[ResearchSourceKind] = Field(min_length=1, max_length=2)

    @field_validator("research_questions", "missing_fact_descriptions")
    @classmethod
    def validate_text_items(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 500 for value in normalized):
            raise ValueError("research text items must contain 1 to 500 characters")
        return normalized

    @model_validator(mode="after")
    def lists_are_unique(self) -> ResearchRequestSpec:
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("source_event_ids must be unique")
        if len(self.allowed_source_kinds) != len(set(self.allowed_source_kinds)):
            raise ValueError("allowed_source_kinds must be unique")
        return self


class ResearchRequestPayload(StrictModel):
    request_id: UUID
    trigger: ResearchTrigger
    source_event_ids: list[UUID]
    research_questions: list[str]
    missing_fact_descriptions: list[str]
    current_fact_snapshot: ResearchFactSnapshot
    allowed_source_kinds: list[ResearchSourceKind]

    @model_validator(mode="after")
    def snapshot_matches_request(self) -> ResearchRequestPayload:
        if {item.event_id for item in self.current_fact_snapshot.events} != set(
            self.source_event_ids
        ):
            raise ValueError("snapshot events must exactly match source_event_ids")
        return self


class ResearchCandidate(StrictModel):
    source_kind: ResearchSourceKind
    source_url: str = Field(min_length=1, max_length=2048)
    relevance_summary: str = Field(min_length=1, max_length=500)


class ResearchDiscovery(StrictModel):
    schema_version: Literal["research_discovery.v1"] = "research_discovery.v1"
    request_id: UUID
    candidates: list[ResearchCandidate] = Field(max_length=12)


class RuntimeUsage(StrictModel):
    input: int = Field(default=0, ge=0)
    output: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)


class ResearchDiscoveryResponse(StrictModel):
    payload: ResearchDiscovery
    provider: str | None
    model: str | None
    usage: RuntimeUsage


def canonical_json_bytes(value: StrictModel | dict[str, object]) -> bytes:
    document = value.model_dump(mode="json") if isinstance(value, StrictModel) else value
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def request_input_hash(payload: ResearchRequestPayload) -> str:
    document = payload.model_dump(mode="json", exclude={"request_id"})
    return sha256(canonical_json_bytes(document)).hexdigest()
