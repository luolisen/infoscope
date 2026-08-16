from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.db import get_session
from infoscope.models import User
from infoscope.schemas.brief import BriefLatestItem, BriefLatestResponse
from infoscope.services.brief import BriefRepository


class BriefApiService:
    def __init__(self, database: AsyncSession) -> None:
        self.repository = BriefRepository(database)

    async def latest(self, user: User) -> BriefLatestResponse:
        artifact, rows = await self.repository.latest_items(user.id)
        if artifact is None:
            return BriefLatestResponse(generated_at=None, items=[])
        return BriefLatestResponse(
            generated_at=artifact.created_at,
            items=[
                BriefLatestItem(
                    event_id=item.event_id,
                    title=item.snapshot_title,
                    summary=item.summary,
                    why_it_matters=item.why_it_matters,
                )
                for item in rows
            ],
        )


def get_brief_api_service(
    database: Annotated[AsyncSession, Depends(get_session)],
) -> BriefApiService:
    return BriefApiService(database)
