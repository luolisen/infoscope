from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import (
    BaseAnalysis,
    Claim,
    Event,
    EventSave,
    PersonalizationArtifact,
    PersonalizationRun,
    PersonalizedEvent,
    User,
)
from infoscope.schemas.archive_search import ArchiveResponse, EventSearchResponse
from infoscope.schemas.now import EventSummary
from infoscope.services.personalization import PersonalizationRepository

_WHITESPACE = re.compile(r"\s+")


class ArchiveSearchService:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database
        self.personalization = PersonalizationRepository(database)

    async def archive(self, user: User, *, limit: int, cursor: str | None) -> ArchiveResponse:
        source, after = await self._page_source(
            user.id,
            cursor,
            kind="archive",
            error_code="ARCHIVE_CURSOR_INVALID",
        )
        if source is None:
            return ArchiveResponse(items=[], next_cursor=None)
        historical, ranked = self._historical_view(user.id, source)
        saved = exists(
            select(EventSave.id).where(
                EventSave.user_id == user.id,
                EventSave.event_id == historical.event_id,
            )
        )
        currently_relevant = exists(
            select(PersonalizedEvent.id).where(
                PersonalizedEvent.artifact_id == source.id,
                PersonalizedEvent.user_id == user.id,
                PersonalizedEvent.event_id == historical.event_id,
                PersonalizedEvent.relevant.is_(True),
            )
        )
        query = select(historical, saved.label("saved")).where(
            ranked.c.history_rank == 1,
            or_(saved, ~currently_relevant),
        )
        query = self._after(query, historical, after)
        rows = (
            await self.database.execute(
                query.order_by(historical.snapshot_display_time.desc(), historical.event_id).limit(
                    limit + 1
                )
            )
        ).all()
        page, has_more = rows[:limit], len(rows) > limit
        return ArchiveResponse(
            items=[self._summary(item, saved_value) for item, saved_value in page],
            next_cursor=self._next_cursor(
                source,
                page,
                has_more=has_more,
                kind="archive",
            ),
        )

    async def search(
        self,
        user: User,
        *,
        query_text: str,
        limit: int,
        cursor: str | None,
    ) -> EventSearchResponse:
        normalized = self.normalize_query(query_text)
        query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        source, after = await self._page_source(
            user.id,
            cursor,
            kind="search_events",
            error_code="SEARCH_CURSOR_INVALID",
            query_hash=query_hash,
        )
        if source is None:
            return EventSearchResponse(items=[], next_cursor=None)
        historical, ranked = self._historical_view(user.id, source)
        escaped = self._escape_like(normalized)
        pattern = f"%{escaped}%"
        saved = exists(
            select(EventSave.id).where(
                EventSave.user_id == user.id,
                EventSave.event_id == historical.event_id,
            )
        )
        claim_match = exists(
            select(Claim.id).where(
                Claim.event_id == historical.event_id,
                Claim.text.ilike(pattern, escape="\\"),
            )
        )
        query = (
            select(historical, saved.label("saved"))
            .join(Event, Event.id == historical.event_id)
            .outerjoin(BaseAnalysis, BaseAnalysis.event_id == historical.event_id)
            .where(
                ranked.c.history_rank == 1,
                or_(
                    Event.title.ilike(pattern, escape="\\"),
                    Event.overview.ilike(pattern, escape="\\"),
                    BaseAnalysis.summary.ilike(pattern, escape="\\"),
                    claim_match,
                ),
            )
        )
        query = self._after(query, historical, after)
        rows = (
            await self.database.execute(
                query.order_by(historical.snapshot_display_time.desc(), historical.event_id).limit(
                    limit + 1
                )
            )
        ).all()
        page, has_more = rows[:limit], len(rows) > limit
        return EventSearchResponse(
            items=[self._summary(item, saved_value) for item, saved_value in page],
            next_cursor=self._next_cursor(
                source,
                page,
                has_more=has_more,
                kind="search_events",
                query_hash=query_hash,
            ),
        )

    async def _page_source(
        self,
        user_id: UUID,
        cursor: str | None,
        *,
        kind: Literal["archive", "search_events"],
        error_code: str,
        query_hash: str | None = None,
    ) -> tuple[PersonalizationArtifact | None, tuple[datetime, UUID] | None]:
        if cursor is None:
            return await self.personalization.latest_artifact(user_id), None
        document = self._decode_cursor(cursor, kind=kind, error_code=error_code)
        if query_hash is not None and not hmac.compare_digest(document["query_hash"], query_hash):
            raise self._invalid_cursor(error_code)
        source = (
            await self.database.execute(
                select(PersonalizationArtifact)
                .join(
                    PersonalizationRun,
                    PersonalizationRun.id == PersonalizationArtifact.created_by_run_id,
                )
                .where(
                    PersonalizationArtifact.id
                    == UUID(document["source_personalization_artifact_id"]),
                    PersonalizationArtifact.user_id == user_id,
                    PersonalizationRun.status == "completed",
                )
            )
        ).scalar_one_or_none()
        if source is None:
            raise self._invalid_cursor(error_code)
        return source, (
            datetime.fromisoformat(document["display_time"]),
            UUID(document["event_id"]),
        )

    @staticmethod
    def _historical_view(user_id: UUID, source: PersonalizationArtifact) -> tuple[Any, Any]:
        eligible = (PersonalizationArtifact.created_at < source.created_at) | (
            (PersonalizationArtifact.created_at == source.created_at)
            & (PersonalizationArtifact.id <= source.id)
        )
        ranked = (
            select(
                PersonalizedEvent,
                func.row_number()
                .over(
                    partition_by=PersonalizedEvent.event_id,
                    order_by=(
                        PersonalizationArtifact.created_at.desc(),
                        PersonalizationArtifact.id.desc(),
                    ),
                )
                .label("history_rank"),
            )
            .join(
                PersonalizationArtifact,
                PersonalizationArtifact.id == PersonalizedEvent.artifact_id,
            )
            .join(
                PersonalizationRun,
                PersonalizationRun.id == PersonalizationArtifact.created_by_run_id,
            )
            .where(
                PersonalizedEvent.user_id == user_id,
                PersonalizedEvent.relevant.is_(True),
                PersonalizationRun.status == "completed",
                eligible,
            )
            .subquery()
        )
        return aliased(PersonalizedEvent, ranked), ranked

    @staticmethod
    def _after(query, historical, after: tuple[datetime, UUID] | None):
        if after is None:
            return query
        display_time, event_id = after
        return query.where(
            (historical.snapshot_display_time < display_time)
            | (
                (historical.snapshot_display_time == display_time)
                & (historical.event_id > event_id)
            )
        )

    @classmethod
    def _next_cursor(
        cls,
        source: PersonalizationArtifact,
        page: list[Any],
        *,
        has_more: bool,
        kind: Literal["archive", "search_events"],
        query_hash: str | None = None,
    ) -> str | None:
        if not has_more or not page:
            return None
        last = page[-1][0]
        document: dict[str, Any] = {
            "v": 1,
            "kind": kind,
            "source_personalization_artifact_id": str(source.id),
            "display_time": last.snapshot_display_time.isoformat(),
            "event_id": str(last.event_id),
        }
        if query_hash is not None:
            document["query_hash"] = query_hash
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @classmethod
    def _decode_cursor(
        cls,
        cursor: str,
        *,
        kind: Literal["archive", "search_events"],
        error_code: str,
    ) -> dict[str, Any]:
        expected = {
            "v",
            "kind",
            "source_personalization_artifact_id",
            "display_time",
            "event_id",
        }
        if kind == "search_events":
            expected.add("query_hash")
        try:
            padding = "=" * (-len(cursor) % 4)
            document = json.loads(base64.urlsafe_b64decode(cursor + padding))
            if not isinstance(document, dict) or set(document) != expected:
                raise ValueError
            if document["v"] != 1 or document["kind"] != kind:
                raise ValueError
            UUID(document["source_personalization_artifact_id"])
            UUID(document["event_id"])
            timestamp = datetime.fromisoformat(document["display_time"])
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError
            if kind == "search_events" and not re.fullmatch(
                r"[0-9a-f]{64}", document["query_hash"]
            ):
                raise ValueError
            return document
        except (
            binascii.Error,
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            ValueError,
        ) as error:
            raise cls._invalid_cursor(error_code) from error

    @staticmethod
    def normalize_query(value: str) -> str:
        normalized = _WHITESPACE.sub(" ", value.strip())
        if not normalized or len(normalized) > 200:
            raise ApiError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="SEARCH_QUERY_INVALID",
                message="The search query is invalid.",
            )
        return normalized

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _summary(item: PersonalizedEvent, saved: bool) -> EventSummary:
        return EventSummary(
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
            saved=saved,
        )

    @staticmethod
    def _invalid_cursor(error_code: str) -> ApiError:
        return ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=error_code,
            message="The cursor is invalid.",
        )


def get_archive_search_service(
    database: Annotated[AsyncSession, Depends(get_session)],
) -> ArchiveSearchService:
    return ArchiveSearchService(database)
