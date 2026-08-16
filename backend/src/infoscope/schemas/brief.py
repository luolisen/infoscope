from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BriefLatestItem(BaseModel):
    event_id: UUID
    title: str
    summary: str
    why_it_matters: str


class BriefLatestResponse(BaseModel):
    generated_at: datetime | None
    items: list[BriefLatestItem]
