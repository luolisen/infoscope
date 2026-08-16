from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.db import get_session
from infoscope.errors import ApiError
from infoscope.models import (
    BaseAnalysis,
    Claim,
    ClaimSignal,
    Conflict,
    ConflictClaim,
    ConflictSignal,
    Event,
    EventSignal,
    Signal,
    TimelineClaim,
    TimelineEntry,
    User,
)
from infoscope.schemas.event_detail import (
    EventDetailBaseAnalysis,
    EventDetailClaim,
    EventDetailConflict,
    EventDetailEntity,
    EventDetailEvidence,
    EventDetailResponse,
    EventDetailTimelineEntry,
    EvidencePlatform,
)
from infoscope.services.event_access import EventAccessPolicy


class EventDetailService:
    def __init__(
        self,
        database: AsyncSession,
        access_policy: EventAccessPolicy | None = None,
    ) -> None:
        self.database = database
        self.access_policy = access_policy or EventAccessPolicy(database)

    async def get(self, user: User, event_id: UUID) -> EventDetailResponse:
        await self.access_policy.require_all(user, [event_id])
        event = await self.database.scalar(select(Event).where(Event.id == event_id))
        if event is None:
            raise self._not_found()
        analysis = await self.database.scalar(
            select(BaseAnalysis).where(BaseAnalysis.event_id == event_id)
        )
        if analysis is None:
            raise ApiError(
                status_code=status.HTTP_409_CONFLICT,
                code="EVENT_NOT_READY",
                message="Event detail is not ready.",
            )

        claims = list(
            (
                await self.database.execute(
                    select(Claim)
                    .where(Claim.event_id == event_id)
                    .order_by(Claim.created_at, Claim.id)
                )
            ).scalars()
        )
        timeline = list(
            (
                await self.database.execute(
                    select(TimelineEntry)
                    .where(TimelineEntry.event_id == event_id)
                    .order_by(TimelineEntry.occurred_at, TimelineEntry.id)
                )
            ).scalars()
        )
        conflicts = list(
            (
                await self.database.execute(
                    select(Conflict)
                    .where(Conflict.event_id == event_id)
                    .order_by(Conflict.created_at, Conflict.id)
                )
            ).scalars()
        )
        signals = list(
            (
                await self.database.execute(
                    select(Signal)
                    .join(EventSignal, EventSignal.signal_id == Signal.id)
                    .where(EventSignal.event_id == event_id)
                    .order_by(
                        Signal.published_at.desc().nulls_last(),
                        Signal.created_at.desc(),
                        Signal.id,
                    )
                )
            ).scalars()
        )

        claim_ids = [item.id for item in claims]
        timeline_ids = [item.id for item in timeline]
        conflict_ids = [item.id for item in conflicts]
        claim_signal_rows = await self._pairs(
            ClaimSignal.claim_id,
            ClaimSignal.signal_id,
            ClaimSignal.claim_id.in_(claim_ids),
            enabled=bool(claim_ids),
        )
        timeline_claim_rows = await self._pairs(
            TimelineClaim.timeline_entry_id,
            TimelineClaim.claim_id,
            TimelineClaim.timeline_entry_id.in_(timeline_ids),
            enabled=bool(timeline_ids),
        )
        conflict_claim_rows = await self._pairs(
            ConflictClaim.conflict_id,
            ConflictClaim.claim_id,
            ConflictClaim.conflict_id.in_(conflict_ids),
            enabled=bool(conflict_ids),
        )
        conflict_signal_rows = await self._pairs(
            ConflictSignal.conflict_id,
            ConflictSignal.signal_id,
            ConflictSignal.conflict_id.in_(conflict_ids),
            enabled=bool(conflict_ids),
        )
        return self._response(
            event=event,
            analysis=analysis,
            claims=claims,
            timeline=timeline,
            conflicts=conflicts,
            signals=signals,
            claim_signal_rows=claim_signal_rows,
            timeline_claim_rows=timeline_claim_rows,
            conflict_claim_rows=conflict_claim_rows,
            conflict_signal_rows=conflict_signal_rows,
        )

    async def _pairs(self, left, right, condition, *, enabled: bool) -> list[tuple[UUID, UUID]]:
        if not enabled:
            return []
        return list((await self.database.execute(select(left, right).where(condition))).all())

    def _response(
        self,
        *,
        event: Event,
        analysis: BaseAnalysis,
        claims: list[Claim],
        timeline: list[TimelineEntry],
        conflicts: list[Conflict],
        signals: list[Signal],
        claim_signal_rows: list[tuple[UUID, UUID]],
        timeline_claim_rows: list[tuple[UUID, UUID]],
        conflict_claim_rows: list[tuple[UUID, UUID]],
        conflict_signal_rows: list[tuple[UUID, UUID]],
    ) -> EventDetailResponse:
        claim_order = {item.id: index for index, item in enumerate(claims)}
        evidence_order = {item.id: index for index, item in enumerate(signals)}
        timeline_set = {item.id for item in timeline}
        conflict_set = {item.id for item in conflicts}
        if (
            len(claim_order) != len(claims)
            or len(timeline_set) != len(timeline)
            or len(conflict_set) != len(conflicts)
            or len(evidence_order) != len(signals)
        ):
            raise self._integrity_error()
        self._validate_pairs(claim_signal_rows, set(claim_order), set(evidence_order))
        self._validate_pairs(timeline_claim_rows, timeline_set, set(claim_order))
        self._validate_pairs(conflict_claim_rows, conflict_set, set(claim_order))
        self._validate_pairs(conflict_signal_rows, conflict_set, set(evidence_order))

        claim_evidence = self._relations(claim_signal_rows, evidence_order)
        timeline_claims = self._relations(timeline_claim_rows, claim_order)
        conflict_claims = self._relations(conflict_claim_rows, claim_order)
        conflict_evidence = self._relations(conflict_signal_rows, evidence_order)
        try:
            base_analysis = EventDetailBaseAnalysis(
                summary=analysis.summary,
                event_type=analysis.event_type,
                importance=analysis.importance,
                topics=analysis.topics,
                entities=[EventDetailEntity.model_validate(item) for item in analysis.entities],
            )
            return EventDetailResponse(
                id=event.id,
                title=event.title,
                overview=event.overview,
                state=event.state,
                display_time=self._utc(event.display_time),
                updated_at=self._utc(event.updated_at),
                base_analysis=base_analysis,
                why_it_matters=analysis.summary,
                topics=list(analysis.topics),
                saved=False,
                claims=[
                    EventDetailClaim(
                        id=item.id,
                        text=item.text,
                        state=item.state,
                        evidence_ids=claim_evidence.get(item.id, []),
                    )
                    for item in claims
                ],
                timeline=[
                    EventDetailTimelineEntry(
                        id=item.id,
                        occurred_at=self._utc(item.occurred_at),
                        summary=item.summary,
                        claim_ids=timeline_claims.get(item.id, []),
                    )
                    for item in timeline
                ],
                conflicts=[
                    EventDetailConflict(
                        id=item.id,
                        claim_ids=conflict_claims.get(item.id, []),
                        summary=item.summary,
                        evidence_ids=conflict_evidence.get(item.id, []),
                    )
                    for item in conflicts
                ],
                evidence=[self._evidence(item) for item in signals],
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise self._integrity_error() from error

    @staticmethod
    def _validate_pairs(
        rows: list[tuple[UUID, UUID]], left: set[UUID], right: set[UUID]
    ) -> None:
        if len(rows) != len(set(rows)) or any(a not in left or b not in right for a, b in rows):
            raise EventDetailService._integrity_error()

    @staticmethod
    def _relations(
        rows: list[tuple[UUID, UUID]], target_order: dict[UUID, int]
    ) -> dict[UUID, list[UUID]]:
        result: dict[UUID, list[UUID]] = {}
        for owner_id, target_id in rows:
            result.setdefault(owner_id, []).append(target_id)
        for values in result.values():
            values.sort(key=target_order.__getitem__)
        return result

    @classmethod
    def _evidence(cls, signal: Signal) -> EventDetailEvidence:
        visibility = signal.evidence_visibility
        if not signal.normalized_text.strip():
            raise cls._integrity_error()
        if visibility == "private_sanitized":
            if signal.source_type != "telegram" or signal.public_provenance is not None:
                raise cls._integrity_error()
            return EventDetailEvidence(
                id=signal.id,
                platform=EvidencePlatform.TELEGRAM,
                visibility=visibility,
                author_name=None,
                url=None,
                published_at=cls._optional_utc(signal.published_at),
                excerpt=signal.normalized_text,
            )
        if visibility != "public" or not isinstance(signal.public_provenance, dict):
            raise cls._integrity_error()
        provenance = signal.public_provenance
        if signal.source_type == "telegram":
            cls._allow_keys(provenance, {"platform", "chat_title", "chat_username", "url"})
            source_platform = provenance.get("platform")
            if not isinstance(source_platform, str) or source_platform.casefold() != "telegram":
                raise cls._integrity_error()
            platform = EvidencePlatform.TELEGRAM
            author_name = cls._optional_string(provenance.get("chat_title"))
            cls._optional_string(provenance.get("chat_username"))
            url = cls._optional_string(provenance.get("url"))
        elif signal.source_type == "trend_radar":
            cls._allow_keys(provenance, {"source_kind", "source_name", "url"})
            source_kind = provenance.get("source_kind")
            if source_kind not in {"rss", "hotlist"}:
                raise cls._integrity_error()
            platform = EvidencePlatform.RSS if source_kind == "rss" else EvidencePlatform.WEB
            author_name = cls._optional_string(provenance.get("source_name"))
            url = cls._optional_string(provenance.get("url"))
        elif signal.source_type == "research":
            cls._allow_keys(provenance, {"source_kind", "canonical_url"})
            if provenance.get("source_kind") not in {"web_page", "github_document"}:
                raise cls._integrity_error()
            platform = EvidencePlatform.WEB
            author_name = None
            url = cls._required_string(provenance.get("canonical_url"))
        else:
            raise cls._integrity_error()
        return EventDetailEvidence(
            id=signal.id,
            platform=platform,
            visibility=visibility,
            author_name=author_name,
            url=url,
            published_at=cls._optional_utc(signal.published_at),
            excerpt=signal.normalized_text,
        )

    @staticmethod
    def _allow_keys(value: dict[str, Any], allowed: set[str]) -> None:
        if not set(value) <= allowed:
            raise EventDetailService._integrity_error()

    @staticmethod
    def _optional_string(value: object) -> str | None:
        if value is None:
            return None
        return EventDetailService._required_string(value)

    @staticmethod
    def _required_string(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EventDetailService._integrity_error()
        return value.strip()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise EventDetailService._integrity_error()
        return value.astimezone(UTC)

    @classmethod
    def _optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else cls._utc(value)

    @staticmethod
    def _not_found() -> ApiError:
        return ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="EVENT_NOT_FOUND",
            message="Event was not found.",
        )

    @staticmethod
    def _integrity_error() -> ApiError:
        return ApiError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An internal server error occurred.",
        )


def get_event_detail_service(
    database: Annotated[AsyncSession, Depends(get_session)],
) -> EventDetailService:
    return EventDetailService(database)
