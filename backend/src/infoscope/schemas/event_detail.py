from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from infoscope.schemas.now import EventState


class BaseAnalysisImportance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClaimState(StrEnum):
    CONFIRMED = "confirmed"
    UNRESOLVED = "unresolved"
    CONFLICTING = "conflicting"
    CONTRADICTED = "contradicted"


class EvidencePlatform(StrEnum):
    TELEGRAM = "telegram"
    X = "x"
    YOUTUBE = "youtube"
    WEB = "web"
    RSS = "rss"


class EvidenceVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE_SANITIZED = "private_sanitized"


class EventDetailEntity(BaseModel):
    name: str
    entity_type: str


class EventDetailBaseAnalysis(BaseModel):
    summary: str
    event_type: str
    importance: BaseAnalysisImportance
    topics: list[str]
    entities: list[EventDetailEntity]


class EventDetailClaim(BaseModel):
    id: UUID
    text: str
    state: ClaimState
    evidence_ids: list[UUID]


class EventDetailTimelineEntry(BaseModel):
    id: UUID
    occurred_at: datetime
    summary: str
    claim_ids: list[UUID]


class EventDetailConflict(BaseModel):
    id: UUID
    claim_ids: list[UUID]
    summary: str
    evidence_ids: list[UUID]


class EventDetailEvidence(BaseModel):
    id: UUID
    platform: EvidencePlatform
    visibility: EvidenceVisibility
    author_name: str | None
    url: str | None
    published_at: datetime | None
    excerpt: str


class EventDetailResponse(BaseModel):
    id: UUID
    title: str
    overview: str
    state: EventState
    display_time: datetime
    updated_at: datetime
    base_analysis: EventDetailBaseAnalysis
    why_it_matters: str
    topics: list[str]
    saved: bool
    claims: list[EventDetailClaim]
    timeline: list[EventDetailTimelineEntry]
    conflicts: list[EventDetailConflict]
    evidence: list[EventDetailEvidence]
