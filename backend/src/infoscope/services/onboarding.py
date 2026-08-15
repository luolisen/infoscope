from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import User
from infoscope.schemas.onboarding import (
    FOCUS_OPTIONS,
    INVESTMENT_MARKET_OPTIONS,
    SCOPE_OPTIONS,
    FocusId,
    InvestmentMarketId,
    OnboardingAnswers,
    OnboardingResponse,
    OnboardingSelection,
    ScopeId,
)


class OnboardingService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    def get_onboarding(self, user: User) -> OnboardingResponse:
        return self._response(user)

    async def update_onboarding(
        self, user: User, selection: OnboardingSelection
    ) -> OnboardingResponse:
        self._apply_selection(user, selection)
        user.onboarding_completed = True
        user.personalization_update_requested_at = datetime.now(UTC)
        await self.database.commit()
        return self._response(user)

    def get_scope(self, user: User) -> OnboardingResponse:
        self._require_completed(user)
        return self._response(user)

    async def update_scope(
        self, user: User, selection: OnboardingSelection
    ) -> OnboardingResponse:
        self._require_completed(user)
        self._apply_selection(user, selection)
        user.personalization_update_requested_at = datetime.now(UTC)
        await self.database.commit()
        return self._response(user)

    @staticmethod
    def _apply_selection(user: User, selection: OnboardingSelection) -> None:
        user.scope_ids = [value.value for value in selection.scope_ids]
        user.investment_market_ids = [
            value.value for value in selection.investment_market_ids
        ]
        user.focus_ids = [value.value for value in selection.focus_ids]

    @staticmethod
    def _response(user: User) -> OnboardingResponse:
        return OnboardingResponse(
            completed=user.onboarding_completed,
            scope_options=SCOPE_OPTIONS,
            investment_market_options=INVESTMENT_MARKET_OPTIONS,
            focus_options=FOCUS_OPTIONS,
            answers=OnboardingAnswers(
                scope_ids=[ScopeId(value) for value in user.scope_ids],
                investment_market_ids=[
                    InvestmentMarketId(value) for value in user.investment_market_ids
                ],
                focus_ids=[FocusId(value) for value in user.focus_ids],
            ),
        )

    @staticmethod
    def _require_completed(user: User) -> None:
        if not user.onboarding_completed:
            raise ApiError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="ONBOARDING_REQUIRED",
                message="Onboarding must be completed before accessing this resource.",
            )


def get_onboarding_service(
    database: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingService:
    return OnboardingService(database)
