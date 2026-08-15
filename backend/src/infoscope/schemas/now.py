from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EventState(StrEnum):
    DEVELOPING = "developing"
    CONFIRMED = "confirmed"
    CONFLICTING = "conflicting"
    COOLING = "cooling"


class WindowStats(BaseModel):
    window_started_at: datetime
    window_ended_at: datetime
    raw_information_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    relevant_event_count: int = Field(ge=0)


class EventSummary(BaseModel):
    id: str
    title: str
    overview: str
    state: EventState
    display_time: datetime
    updated_at: datetime
    why_it_matters: str
    new_claim_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    topics: list[str]
    saved: bool


class NowResponse(BaseModel):
    window_stats: WindowStats
    items: list[EventSummary]
    next_cursor: str | None
