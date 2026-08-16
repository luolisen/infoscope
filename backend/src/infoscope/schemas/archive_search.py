from uuid import UUID

from pydantic import BaseModel, StrictBool

from infoscope.schemas.now import EventSummary


class EventSavedRequest(BaseModel):
    saved: StrictBool


class EventSavedResponse(BaseModel):
    event_id: UUID
    saved: bool


class ArchiveResponse(BaseModel):
    items: list[EventSummary]
    next_cursor: str | None


class EventSearchResponse(BaseModel):
    items: list[EventSummary]
    next_cursor: str | None
