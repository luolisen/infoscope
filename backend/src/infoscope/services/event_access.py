from __future__ import annotations

from uuid import UUID

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.errors import ApiError
from infoscope.models import Event, User


class EventAccessPolicy:
    """Shared-catalog v1 policy behind a replaceable authorization boundary."""

    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def require_all(self, user: User, event_ids: list[UUID]) -> None:
        _ = user
        available = set(
            (
                await self.database.execute(select(Event.id).where(Event.id.in_(event_ids)))
            ).scalars()
        )
        if available != set(event_ids):
            raise ApiError(
                status_code=status.HTTP_404_NOT_FOUND,
                code="EVENT_NOT_FOUND",
                message="Event was not found.",
            )
