from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.localization_schemas import EventLocalizationItem, canonical_hash
from infoscope.models import Event, EventLocalization


def event_localization_item(event: Event) -> EventLocalizationItem:
    return EventLocalizationItem(
        event_id=event.id,
        title=event.title,
        overview=event.overview,
        state=event.state,
        display_time=event.display_time,
        updated_at=event.updated_at,
    )


def event_localization_hash(event: Event) -> str:
    return canonical_hash(event_localization_item(event))


async def current_event_localizations(
    database: AsyncSession,
    events: Sequence[Event],
    *,
    lock: bool = False,
) -> dict[UUID, tuple[str, str]]:
    if not events:
        return {}
    event_by_id = {event.id: event for event in events}
    query = select(EventLocalization).where(
        EventLocalization.event_id.in_(event_by_id),
        EventLocalization.locale == "zh-CN",
    )
    if lock:
        query = query.with_for_update()
    projections = list((await database.execute(query)).scalars())
    return {
        projection.event_id: (projection.title, projection.overview)
        for projection in projections
        if projection.event_input_hash == event_localization_hash(event_by_id[projection.event_id])
    }
