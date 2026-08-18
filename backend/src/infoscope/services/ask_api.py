from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.ask_schemas import AskFinalAnswerPayload, AskRequestSpec, ask_input_hash
from infoscope.config import Settings, get_settings
from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import AskFinalArtifact, AskRequest, AskRequestEvent, User
from infoscope.schemas.ask import (
    AskAcceptedResponse,
    AskCompletedResponse,
    AskCreateRequest,
    AskFailedResponse,
    AskHistoryItem,
    AskHistoryResponse,
    AskPendingResponse,
    AskProgress,
    AskResult,
    AskRunningResponse,
    AskStatusResponse,
)
from infoscope.schemas.common import ErrorDetail
from infoscope.services.ask_comparison import (
    AskComparisonError,
    AskComparisonRepository,
)
from infoscope.services.event_access import EventAccessPolicy


class AskService:
    def __init__(
        self,
        database: AsyncSession,
        settings: Settings,
        access_policy: EventAccessPolicy | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.access_policy = access_policy or EventAccessPolicy(database)

    async def create(self, user: User, value: AskCreateRequest) -> AskAcceptedResponse:
        ask_id = uuid4()
        repository = AskComparisonRepository(self.database)
        try:
            await self.access_policy.require_all(user, value.event_ids)
        except ApiError as error:
            raise ApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="ASK_EVENT_NOT_AVAILABLE",
                message="A selected Event is not available.",
            ) from error
        try:
            snapshot = await repository.input_snapshot(
                ask_id=ask_id,
                question=value.question,
                selected_event_ids=value.event_ids,
                grok_enabled=value.grok_enabled,
            )
        except AskComparisonError as error:
            if error.error_code == "ASK_EVENT_NOT_FOUND":
                raise ApiError(
                    status_code=status.HTTP_404_NOT_FOUND,
                    code="ASK_EVENT_NOT_AVAILABLE",
                    message="A selected Event is not available.",
                ) from error
            if error.error_code == "ASK_EVENT_BASE_ANALYSIS_MISSING":
                raise ApiError(
                    status_code=status.HTTP_409_CONFLICT,
                    code="ASK_EVENT_NOT_READY",
                    message="A selected Event is not ready for Ask.",
                ) from error
            raise ApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="ASK_EVENT_NOT_READY",
                message="A selected Event is not ready for Ask.",
            ) from error
        spec = AskRequestSpec(
            user_id=user.id,
            question=value.question,
            selected_event_ids=value.event_ids,
            grok_enabled=value.grok_enabled,
        )
        await repository.create_request(
            spec,
            ask_id=ask_id,
            input_hash=ask_input_hash(snapshot),
            max_attempts=self.settings.ask_comparison_max_attempts,
        )
        return AskAcceptedResponse(ask_id=ask_id)

    async def get(self, user: User, ask_id: UUID, request_id: str) -> AskStatusResponse:
        request = (
            await self.database.execute(
                select(AskRequest).where(
                    AskRequest.id == ask_id,
                    AskRequest.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if request is None:
            raise ApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="ASK_NOT_FOUND",
                message="Ask request was not found.",
            )
        progress = self._progress(request)
        if request.status == "pending":
            return AskPendingResponse(ask_id=request.id, status="pending", progress=progress)
        if request.status == "running":
            return AskRunningResponse(ask_id=request.id, status="running", progress=progress)
        if request.status == "failed":
            message = (
                "Research is temporarily unavailable. Please try again later."
                if request.error_code == "ASK_RESEARCH_CAPABILITY_UNAVAILABLE"
                else "Ask processing failed."
            )
            return AskFailedResponse(
                ask_id=request.id,
                status="failed",
                progress=progress,
                error=ErrorDetail(
                    code="ASK_FAILED",
                    message=message,
                    request_id=request_id,
                ),
            )
        artifact = (
            await self.database.execute(
                select(AskFinalArtifact).where(AskFinalArtifact.ask_request_id == request.id)
            )
        ).scalar_one_or_none()
        if artifact is None:
            raise ApiError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="INTERNAL_SERVER_ERROR",
                message="An internal server error occurred.",
            )
        try:
            payload = AskFinalAnswerPayload.model_validate(artifact.payload)
        except ValidationError as error:
            raise ApiError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="INTERNAL_SERVER_ERROR",
                message="An internal server error occurred.",
            ) from error
        return AskCompletedResponse(
            ask_id=request.id,
            status="completed",
            progress=progress,
            result=AskResult(
                answer=payload.answer,
                event_ids=payload.event_ids,
                claim_ids=payload.claim_ids,
                timeline_ids=payload.timeline_entry_ids,
                conflict_ids=payload.conflict_ids,
                evidence_ids=payload.evidence_signal_ids,
                updated_event_ids=payload.updated_event_ids,
            ),
        )

    async def history(
        self,
        user: User,
        *,
        limit: int,
        cursor: str | None,
    ) -> AskHistoryResponse:
        """Return the owner's independent Ask rounds in stable keyset order.

        The cursor is intentionally opaque to the frontend.  It binds the
        endpoint kind and the last ``(created_at, ask_id)`` tuple, so a cursor
        cannot be reused against another Ask endpoint or silently switch
        ordering semantics.
        """
        after = self._decode_history_cursor(cursor) if cursor is not None else None
        query = select(AskRequest).where(AskRequest.user_id == user.id)
        if after is not None:
            created_at, ask_id = after
            query = query.where(
                (AskRequest.created_at < created_at)
                | ((AskRequest.created_at == created_at) & (AskRequest.id > ask_id))
            )
        rows = (
            await self.database.execute(
                query.order_by(AskRequest.created_at.desc(), AskRequest.id).limit(limit + 1)
            )
        ).scalars().all()
        page = rows[:limit]
        items: list[AskHistoryItem] = []
        for request in page:
            event_rows = (
                await self.database.execute(
                    select(AskRequestEvent.event_id)
                    .where(AskRequestEvent.ask_request_id == request.id)
                    .order_by(AskRequestEvent.position)
                )
            ).scalars().all()
            answer: str | None = None
            updated_event_ids: list[UUID] = []
            if request.status == "completed":
                artifact = (
                    await self.database.execute(
                        select(AskFinalArtifact).where(
                            AskFinalArtifact.ask_request_id == request.id
                        )
                    )
                ).scalar_one_or_none()
                if artifact is not None:
                    try:
                        payload = AskFinalAnswerPayload.model_validate(artifact.payload)
                    except ValidationError:
                        payload = None
                    if payload is not None:
                        answer = payload.answer
                        updated_event_ids = payload.updated_event_ids
            items.append(
                AskHistoryItem(
                    ask_id=request.id,
                    status=request.status,
                    question=request.question,
                    event_ids=list(event_rows),
                    created_at=request.created_at,
                    finished_at=request.finished_at,
                    thinking_seconds=self._elapsed_seconds(request),
                    answer=answer,
                    updated_event_ids=updated_event_ids,
                )
            )
        has_more = len(rows) > limit
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = self._encode_history_cursor(last.created_at, last.id)
        return AskHistoryResponse(items=items, next_cursor=next_cursor)

    @staticmethod
    def _elapsed_seconds(request: AskRequest) -> int:
        finished = request.finished_at or datetime.now(UTC)
        return max(0, int((finished - request.created_at).total_seconds()))

    @classmethod
    def _progress(cls, request: AskRequest) -> AskProgress:
        stages = {
            "comparing": "comparing",
            "awaiting_research": "researching",
            "awaiting_reconciliation": "reconciling",
            "finalizing": "finalizing",
        }
        return AskProgress(
            stage=stages[request.stage],  # type: ignore[arg-type]
            elapsed_seconds=cls._elapsed_seconds(request),
        )

    @staticmethod
    def _encode_history_cursor(created_at: datetime, ask_id: UUID) -> str:
        document = {
            "v": 1,
            "kind": "ask_history",
            "created_at": created_at.isoformat(),
            "ask_id": str(ask_id),
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_history_cursor(cursor: str) -> tuple[datetime, UUID]:
        expected = {"v", "kind", "created_at", "ask_id"}
        try:
            padding = "=" * (-len(cursor) % 4)
            document = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if not isinstance(document, dict) or set(document) != expected:
                raise ValueError
            if document["v"] != 1 or document["kind"] != "ask_history":
                raise ValueError
            timestamp = datetime.fromisoformat(document["created_at"])
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError
            return timestamp, UUID(document["ask_id"])
        except (ValueError, TypeError, KeyError, binascii.Error, json.JSONDecodeError) as error:
            raise ApiError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="ASK_HISTORY_CURSOR_INVALID",
                message="The Ask history cursor is invalid.",
            ) from error


def get_ask_service(
    database: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AskService:
    return AskService(database, settings)
