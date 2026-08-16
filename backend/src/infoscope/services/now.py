from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import PersonalizationArtifact, PersonalizedEvent, User
from infoscope.schemas.now import EventSummary, NowResponse, WindowStats
from infoscope.services.personalization import PersonalizationRepository


class NowService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.personalization = PersonalizationRepository(database)

    async def get_now(self, user: User, *, limit: int, cursor: str | None) -> NowResponse:
        artifact: PersonalizationArtifact | None
        after: tuple[datetime, UUID] | None = None
        if cursor is None:
            artifact = await self.personalization.latest_artifact(user.id)
        else:
            artifact_id, display_time, event_id = self._decode_cursor(cursor)
            artifact = await self.database.get(PersonalizationArtifact, artifact_id)
            if artifact is None or artifact.user_id != user.id:
                raise self._invalid_cursor()
            after = (display_time, event_id)
        if artifact is None:
            window_start, window_end, raw_count = await self.personalization.window_stats()
            return NowResponse(
                window_stats=WindowStats(
                    window_started_at=window_start,
                    window_ended_at=window_end,
                    raw_information_count=raw_count,
                    event_count=0,
                    relevant_event_count=0,
                ),
                items=[],
                next_cursor=None,
            )
        query = select(PersonalizedEvent).where(
            PersonalizedEvent.artifact_id == artifact.id,
            PersonalizedEvent.relevant.is_(True),
        )
        if after is not None:
            display_time, event_id = after
            query = query.where(
                (PersonalizedEvent.snapshot_display_time < display_time)
                | (
                    (PersonalizedEvent.snapshot_display_time == display_time)
                    & (PersonalizedEvent.event_id > event_id)
                )
            )
        rows = list(
            (
                await self.database.execute(
                    query.order_by(
                        PersonalizedEvent.snapshot_display_time.desc(),
                        PersonalizedEvent.event_id,
                    ).limit(limit + 1)
                )
            ).scalars()
        )
        page, has_more = rows[:limit], len(rows) > limit
        items = [
            EventSummary(
                id=item.event_id,
                title=item.snapshot_title,
                overview=item.snapshot_overview,
                state=item.snapshot_state,
                display_time=item.snapshot_display_time,
                updated_at=item.snapshot_event_updated_at,
                why_it_matters=item.why_it_matters or "",
                new_claim_count=item.snapshot_new_claim_count,
                conflict_count=item.snapshot_conflict_count,
                topics=item.snapshot_topics,
                saved=False,
            )
            for item in page
        ]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = self._encode_cursor(
                artifact.id,
                last.snapshot_display_time,
                last.event_id,
            )
        return NowResponse(
            window_stats=WindowStats(
                window_started_at=artifact.window_started_at,
                window_ended_at=artifact.window_ended_at,
                raw_information_count=artifact.raw_information_count,
                event_count=artifact.event_count,
                relevant_event_count=artifact.relevant_event_count,
            ),
            items=items,
            next_cursor=next_cursor,
        )

    @staticmethod
    def _encode_cursor(artifact_id: UUID, display_time: datetime, event_id: UUID) -> str:
        payload = json.dumps(
            {"a": str(artifact_id), "i": str(event_id), "t": display_time.isoformat(), "v": 1},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[UUID, datetime, UUID]:
        try:
            padding = "=" * (-len(cursor) % 4)
            document: Any = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if not isinstance(document, dict) or set(document) != {"a", "i", "t", "v"}:
                raise ValueError
            if document["v"] != 1:
                raise ValueError
            timestamp = datetime.fromisoformat(document["t"])
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError
            return UUID(document["a"]), timestamp, UUID(document["i"])
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise NowService._invalid_cursor() from error

    @staticmethod
    def _invalid_cursor() -> ApiError:
        return ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="NOW_CURSOR_INVALID",
            message="The NOW cursor is invalid.",
        )


def get_now_service(database: Annotated[AsyncSession, Depends(get_session)]) -> NowService:
    return NowService(database)
