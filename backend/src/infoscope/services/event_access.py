from __future__ import annotations

from uuid import UUID

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.errors import ApiError
from infoscope.models import User
from infoscope.services.personalization import PersonalizationRepository


class EventAccessPolicy:
    """Allow Events that were relevant in any completed user snapshot."""

    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def require_all(self, user: User, event_ids: list[UUID]) -> None:
        repository = PersonalizationRepository(self.database)
        available = {
            event_id
            for event_id in event_ids
            if await repository.was_ever_relevant(user.id, event_id)
        }
        if available != set(event_ids):
            raise ApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="EVENT_NOT_FOUND",
                message="Event was not found.",
            )
