from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from infoscope.schemas.common import ErrorDetail


class AskCreateRequest(BaseModel):
    event_ids: list[UUID] = Field(min_length=1, max_length=8)
    question: str = Field(min_length=1, max_length=2000)
    grok_enabled: bool = False

    @field_validator("event_ids")
    @classmethod
    def event_ids_are_unique(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("event_ids must be unique")
        return values

    @field_validator("question")
    @classmethod
    def question_is_trimmed(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class AskAcceptedResponse(BaseModel):
    ask_id: UUID
    status: Literal["pending"] = "pending"


class AskResult(BaseModel):
    answer: str
    event_ids: list[UUID]
    claim_ids: list[UUID]
    timeline_ids: list[UUID]
    conflict_ids: list[UUID]
    evidence_ids: list[UUID]
    updated_event_ids: list[UUID]


class AskPendingResponse(BaseModel):
    ask_id: UUID
    status: Literal["pending"]
    result: None = None
    error: None = None


class AskRunningResponse(BaseModel):
    ask_id: UUID
    status: Literal["running"]
    result: None = None
    error: None = None


class AskCompletedResponse(BaseModel):
    ask_id: UUID
    status: Literal["completed"]
    result: AskResult
    error: None = None


class AskFailedResponse(BaseModel):
    ask_id: UUID
    status: Literal["failed"]
    result: None = None
    error: ErrorDetail


class AskHistoryItem(BaseModel):
    """Owner-only, public summary of one independent Ask round.

    This deliberately excludes prompts, model metadata, artifact IDs and
    evidence/provenance.  ``answer`` is the already-public Ask answer and is
    present only after a completed round.
    """

    ask_id: UUID
    status: Literal["pending", "running", "completed", "failed"]
    question: str
    event_ids: list[UUID]
    created_at: datetime
    finished_at: datetime | None = None
    answer: str | None = None
    updated_event_ids: list[UUID] = Field(default_factory=list)


class AskHistoryResponse(BaseModel):
    items: list[AskHistoryItem]
    next_cursor: str | None


AskStatusResponse = Annotated[
    AskPendingResponse | AskRunningResponse | AskCompletedResponse | AskFailedResponse,
    Field(discriminator="status"),
]
