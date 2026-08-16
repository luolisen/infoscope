from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.db import get_session
from infoscope.models import EventSave, User
from infoscope.schemas.archive_search import EventSavedResponse
from infoscope.services.event_access import EventAccessPolicy


class EventSaveService:
    def __init__(
        self,
        database: AsyncSession,
        access_policy: EventAccessPolicy | None = None,
    ) -> None:
        self.database = database
        self.access_policy = access_policy or EventAccessPolicy(database)

    async def set_saved(self, user: User, event_id: UUID, *, saved: bool) -> EventSavedResponse:
        await self.access_policy.require_all(user, [event_id])
        if saved:
            await self.database.execute(
                insert(EventSave)
                .values(user_id=user.id, event_id=event_id)
                .on_conflict_do_nothing(index_elements=[EventSave.user_id, EventSave.event_id])
            )
        else:
            await self.database.execute(
                delete(EventSave).where(
                    EventSave.user_id == user.id,
                    EventSave.event_id == event_id,
                )
            )
        final = bool(
            await self.database.scalar(
                select(
                    exists().where(
                        EventSave.user_id == user.id,
                        EventSave.event_id == event_id,
                    )
                )
            )
        )
        await self.database.commit()
        return EventSavedResponse(event_id=event_id, saved=final)


def get_event_save_service(
    database: Annotated[AsyncSession, Depends(get_session)],
) -> EventSaveService:
    return EventSaveService(database)
