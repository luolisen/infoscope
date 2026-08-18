from __future__ import annotations

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
from infoscope.models import AskFinalArtifact, AskRequest, User
from infoscope.schemas.ask import (
    AskAcceptedResponse,
    AskCompletedResponse,
    AskCreateRequest,
    AskFailedResponse,
    AskPendingResponse,
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
        if request.status == "pending":
            return AskPendingResponse(ask_id=request.id, status="pending")
        if request.status == "running":
            return AskRunningResponse(ask_id=request.id, status="running")
        if request.status == "failed":
            message = (
                "Research is temporarily unavailable. Please try again later."
                if request.error_code == "ASK_RESEARCH_CAPABILITY_UNAVAILABLE"
                else "Ask processing failed."
            )
            return AskFailedResponse(
                ask_id=request.id,
                status="failed",
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


def get_ask_service(
    database: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AskService:
    return AskService(database, settings)
