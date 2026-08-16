from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy import case, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.brief_schemas import (
    INPUT_SCHEMA_VERSION,
    MAX_INPUT_BYTES,
    OUTPUT_SCHEMA_VERSION,
    PRIORITY_ORDER,
    BriefBaseAnalysis,
    BriefClaim,
    BriefConflict,
    BriefDecision,
    BriefEventInput,
    BriefInput,
    BriefPayload,
    BriefPersonalization,
    BriefResponse,
    BriefTimelineEntry,
    canonical_bytes,
    canonical_hash,
)
from infoscope.analysis.client import AnalysisError
from infoscope.models import (
    BaseAnalysis,
    BriefArtifact,
    BriefItem,
    BriefRun,
    Claim,
    Conflict,
    ConflictClaim,
    Event,
    PersonalizationArtifact,
    PersonalizationRun,
    PersonalizedEvent,
    TimelineClaim,
    TimelineEntry,
    User,
)

BRIEF_NAMESPACE = UUID("e990b774-d823-4862-964c-c1c3576c23bc")


class BriefError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class BriefClient(Protocol):
    async def generate_brief(self, value: BriefInput) -> BriefResponse: ...


class BriefRepository:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.clock = clock

    async def latest_personalization_artifact(
        self, user_id: UUID, *, lock: bool = False
    ) -> PersonalizationArtifact | None:
        query = (
            select(PersonalizationArtifact)
            .join(
                PersonalizationRun,
                PersonalizationRun.id == PersonalizationArtifact.created_by_run_id,
            )
            .where(
                PersonalizationArtifact.user_id == user_id,
                PersonalizationRun.status == "completed",
            )
            .order_by(PersonalizationArtifact.created_at.desc(), PersonalizationArtifact.id.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update(of=PersonalizationArtifact)
        return (await self.database.execute(query)).scalar_one_or_none()

    async def input_snapshot(
        self,
        user_id: UUID,
        *,
        source_artifact_id: UUID | None = None,
        lock: bool = False,
    ) -> BriefInput:
        user_query = select(User).where(User.id == user_id)
        if lock:
            user_query = user_query.with_for_update()
        user = (await self.database.execute(user_query)).scalar_one_or_none()
        if user is None or not user.onboarding_completed:
            raise BriefError("BRIEF_USER_NOT_READY")
        latest = await self.latest_personalization_artifact(user_id, lock=lock)
        if latest is None:
            raise BriefError("BRIEF_PERSONALIZATION_UNAVAILABLE")
        if source_artifact_id is not None and latest.id != source_artifact_id:
            raise BriefError("BRIEF_SOURCE_SUPERSEDED")
        source = latest
        priority = case(PRIORITY_ORDER, value=PersonalizedEvent.priority, else_=4)
        selected_query = (
            select(PersonalizedEvent)
            .where(
                PersonalizedEvent.artifact_id == source.id,
                PersonalizedEvent.user_id == user_id,
                PersonalizedEvent.relevant.is_(True),
            )
            .order_by(
                priority,
                PersonalizedEvent.snapshot_display_time.desc(),
                PersonalizedEvent.event_id,
            )
            .limit(8)
        )
        if lock:
            selected_query = selected_query.with_for_update()
        personalized = list((await self.database.execute(selected_query)).scalars())
        event_ids = [item.event_id for item in personalized]
        if not event_ids:
            return BriefInput(
                user_id=user_id,
                source_personalization_artifact_id=source.id,
                events=[],
            )
        events = await self._rows_by_id(Event, event_ids, lock=lock)
        analyses = await self._rows_by_event(BaseAnalysis, event_ids, lock=lock)
        claims = await self._facts(Claim, event_ids, Claim.created_at, lock=lock)
        timeline = await self._facts(TimelineEntry, event_ids, TimelineEntry.occurred_at, lock=lock)
        conflicts = await self._facts(Conflict, event_ids, Conflict.created_at, lock=lock)
        claim_ids = [item.id for values in claims.values() for item in values]
        timeline_ids = [item.id for values in timeline.values() for item in values]
        conflict_ids = [item.id for values in conflicts.values() for item in values]
        timeline_claims = await self._relations(
            TimelineClaim,
            TimelineClaim.timeline_entry_id,
            timeline_ids,
            claim_ids,
            lock=lock,
        )
        conflict_claims = await self._relations(
            ConflictClaim,
            ConflictClaim.conflict_id,
            conflict_ids,
            claim_ids,
            lock=lock,
        )
        result: list[BriefEventInput] = []
        for snapshot in personalized:
            event = events.get(snapshot.event_id)
            analysis = analyses.get(snapshot.event_id)
            if event is None or analysis is None:
                raise BriefError("BRIEF_FACTS_INCOMPLETE")
            event_claims = claims.get(event.id, [])
            claim_order = {item.id: index for index, item in enumerate(event_claims)}
            try:
                result.append(
                    BriefEventInput(
                        event_id=event.id,
                        source_personalized_event_id=snapshot.id,
                        personalization=BriefPersonalization(
                            priority=snapshot.priority,
                            why_it_matters=snapshot.why_it_matters,
                            personalized_angle=snapshot.personalized_angle,
                        ),
                        title=event.title,
                        overview=event.overview,
                        state=event.state,
                        display_time=event.display_time,
                        updated_at=event.updated_at,
                        base_analysis=BriefBaseAnalysis(
                            base_analysis_id=analysis.id,
                            summary=analysis.summary,
                            event_type=analysis.event_type,
                            importance=analysis.importance,
                            topics=analysis.topics,
                            entities=analysis.entities,
                        ),
                        claims=[
                            BriefClaim(claim_id=item.id, text=item.text, state=item.state)
                            for item in event_claims
                        ],
                        timeline=[
                            BriefTimelineEntry(
                                timeline_entry_id=item.id,
                                occurred_at=item.occurred_at,
                                summary=item.summary,
                                claim_ids=self._ordered_relations(
                                    timeline_claims.get(item.id, []), claim_order
                                ),
                            )
                            for item in timeline.get(event.id, [])
                        ],
                        conflicts=[
                            BriefConflict(
                                conflict_id=item.id,
                                summary=item.summary,
                                claim_ids=self._ordered_relations(
                                    conflict_claims.get(item.id, []), claim_order
                                ),
                            )
                            for item in conflicts.get(event.id, [])
                        ],
                    )
                )
            except (TypeError, ValueError) as error:
                raise BriefError("BRIEF_INPUT_SCHEMA_INVALID") from error
        value = BriefInput(
            user_id=user_id,
            source_personalization_artifact_id=source.id,
            events=result,
        )
        if len(canonical_bytes(value)) > MAX_INPUT_BYTES:
            raise BriefError("BRIEF_INPUT_LIMIT_EXCEEDED")
        return value

    async def create_or_reuse(self, value: BriefInput, *, max_attempts: int) -> BriefRun:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        user = (
            await self.database.execute(
                select(User).where(User.id == value.user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user is None or not user.onboarding_completed:
            raise BriefError("BRIEF_USER_NOT_READY")
        latest = await self.latest_personalization_artifact(value.user_id, lock=True)
        if latest is None or latest.id != value.source_personalization_artifact_id:
            raise BriefError("BRIEF_SOURCE_SUPERSEDED")
        prior = (
            await self.database.execute(
                select(BriefRun).where(
                    BriefRun.source_personalization_artifact_id
                    == value.source_personalization_artifact_id
                )
            )
        ).scalar_one_or_none()
        if prior is not None:
            await self.database.commit()
            return prior
        input_hash = canonical_hash(value)
        active = (
            await self.database.execute(
                select(BriefRun).where(BriefRun.user_id == user.id, BriefRun.active_slot == 1)
            )
        ).scalar_one_or_none()
        if active is not None:
            raise BriefError("BRIEF_ALREADY_RUNNING", retryable=True)
        run = BriefRun(
            user_id=user.id,
            source_personalization_artifact_id=value.source_personalization_artifact_id,
            idempotency_key=uuid5(
                BRIEF_NAMESPACE, f"{value.source_personalization_artifact_id}:{input_hash}"
            ),
            schema_version=INPUT_SCHEMA_VERSION,
            input_hash=input_hash,
            status="pending",
            active_slot=1,
            max_attempts=max_attempts,
        )
        self.database.add(run)
        await self.database.commit()
        return run

    async def start_attempt(self, run_id: UUID) -> BriefRun:
        run = await self._locked_run(run_id)
        if run.status == "completed":
            return run
        if run.status == "running":
            raise BriefError("BRIEF_ALREADY_RUNNING", retryable=True)
        if run.status == "failed" or run.attempt_count >= run.max_attempts:
            raise BriefError("BRIEF_MAX_ATTEMPTS_REACHED")
        if run.status != "pending":
            raise BriefError("BRIEF_RUN_STATE_INVALID")
        run.status = "running"
        run.attempt_count += 1
        run.started_at = run.started_at or self.clock()
        run.error_code = None
        await self.database.commit()
        return run

    async def persist_success(
        self,
        run_id: UUID,
        original: BriefInput,
        response: BriefResponse | None,
    ) -> BriefRun:
        await self.database.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        run = await self._locked_run(run_id)
        if run.status != "running":
            raise BriefError("BRIEF_RUN_STATE_INVALID")
        current = await self.input_snapshot(
            run.user_id,
            source_artifact_id=run.source_personalization_artifact_id,
            lock=True,
        )
        if current != original or canonical_hash(current) != run.input_hash:
            raise BriefError("BRIEF_INPUT_CHANGED")
        payload = response.payload if response is not None else BriefPayload(items=[])
        self.validate_output(payload, current)
        artifact = BriefArtifact(
            user_id=run.user_id,
            created_by_run_id=run.id,
            source_personalization_artifact_id=run.source_personalization_artifact_id,
            artifact_kind="model" if response is not None else "deterministic_empty",
            schema_version=OUTPUT_SCHEMA_VERSION,
            input_hash=run.input_hash,
            input_payload=current.model_dump(mode="json"),
            output_payload=payload.model_dump(mode="json"),
            provider=response.provider if response else None,
            model=response.model if response else None,
            token_usage=response.token_usage.model_dump(mode="json") if response else None,
        )
        self.database.add(artifact)
        await self.database.flush()
        decisions = {item.event_id: item for item in payload.items}
        source_rows = await self._rows_by_id(
            PersonalizedEvent,
            [item.source_personalized_event_id for item in current.events],
            lock=True,
        )
        self.database.add_all(
            [
                self._brief_item(
                    artifact=artifact,
                    position=position,
                    event=event,
                    source=source_rows[event.source_personalized_event_id],
                    decision=decisions[event.event_id],
                )
                for position, event in enumerate(current.events)
            ]
        )
        run.status = "completed"
        run.active_slot = None
        run.error_code = None
        run.finished_at = self.clock()
        await self.database.commit()
        return run

    async def persist_failure(self, run_id: UUID, error_code: str, *, retryable: bool) -> BriefRun:
        await self.database.rollback()
        run = await self._locked_run(run_id)
        if run.status != "running":
            raise BriefError("BRIEF_RUN_STATE_INVALID")
        terminal = not retryable or run.attempt_count >= run.max_attempts
        run.status = "failed" if terminal else "pending"
        run.active_slot = None if terminal else 1
        run.error_code = error_code[:128]
        run.finished_at = self.clock() if terminal else None
        await self.database.commit()
        return run

    async def latest_items(self, user_id: UUID) -> tuple[BriefArtifact | None, list[BriefItem]]:
        latest = await self.latest_personalization_artifact(user_id)
        if latest is None:
            return None, []
        artifact = (
            await self.database.execute(
                select(BriefArtifact).where(
                    BriefArtifact.user_id == user_id,
                    BriefArtifact.source_personalization_artifact_id == latest.id,
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            return None, []
        items = list(
            (
                await self.database.execute(
                    select(BriefItem)
                    .where(BriefItem.artifact_id == artifact.id)
                    .order_by(BriefItem.position)
                )
            ).scalars()
        )
        return artifact, items

    @staticmethod
    def validate_output(payload: BriefPayload, value: BriefInput) -> None:
        if [item.event_id for item in payload.items] != [item.event_id for item in value.events]:
            raise BriefError("BRIEF_SCHEMA_INVALID", retryable=True)

    @staticmethod
    def _brief_item(
        *,
        artifact: BriefArtifact,
        position: int,
        event: BriefEventInput,
        source: PersonalizedEvent,
        decision: BriefDecision,
    ) -> BriefItem:
        return BriefItem(
            artifact_id=artifact.id,
            user_id=artifact.user_id,
            source_personalization_artifact_id=artifact.source_personalization_artifact_id,
            source_personalized_event_id=source.id,
            event_id=event.event_id,
            position=position,
            snapshot_title=source.snapshot_title,
            summary=decision.summary,
            why_it_matters=event.personalization.why_it_matters,
        )

    async def _locked_run(self, run_id: UUID) -> BriefRun:
        run = (
            await self.database.execute(
                select(BriefRun).where(BriefRun.id == run_id).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None:
            raise BriefError("BRIEF_RUN_NOT_FOUND")
        return run

    async def _rows_by_id(self, model, ids: list[UUID], *, lock: bool) -> dict[UUID, object]:
        if not ids:
            return {}
        query = select(model).where(model.id.in_(ids))
        if lock:
            query = query.with_for_update()
        rows = list((await self.database.execute(query)).scalars())
        if len(rows) != len(ids):
            raise BriefError("BRIEF_FACTS_INCOMPLETE")
        return {item.id: item for item in rows}

    async def _rows_by_event(
        self, model, event_ids: list[UUID], *, lock: bool
    ) -> dict[UUID, object]:
        query = select(model).where(model.event_id.in_(event_ids))
        if lock:
            query = query.with_for_update()
        rows = list((await self.database.execute(query)).scalars())
        if len(rows) != len(event_ids):
            raise BriefError("BRIEF_FACTS_INCOMPLETE")
        return {item.event_id: item for item in rows}

    async def _facts(
        self, model, event_ids: list[UUID], ordering, *, lock: bool
    ) -> dict[UUID, list[object]]:
        query = select(model).where(model.event_id.in_(event_ids)).order_by(ordering, model.id)
        if lock:
            query = query.with_for_update()
        grouped = {event_id: [] for event_id in event_ids}
        for item in (await self.database.execute(query)).scalars():
            grouped[item.event_id].append(item)
        return grouped

    async def _relations(
        self,
        model,
        parent_column,
        parent_ids: list[UUID],
        claim_ids: list[UUID],
        *,
        lock: bool,
    ) -> dict[UUID, list[UUID]]:
        if not parent_ids:
            return {}
        query = select(model).where(parent_column.in_(parent_ids))
        if lock:
            query = query.with_for_update()
        grouped: dict[UUID, list[UUID]] = {item: [] for item in parent_ids}
        claim_scope = set(claim_ids)
        for relation in (await self.database.execute(query)).scalars():
            if relation.claim_id not in claim_scope:
                raise BriefError("BRIEF_RELATION_SCOPE_INVALID")
            grouped[getattr(relation, parent_column.key)].append(relation.claim_id)
        return grouped

    @staticmethod
    def _ordered_relations(values: list[UUID], order: dict[UUID, int]) -> list[UUID]:
        if len(values) != len(set(values)) or not set(values) <= set(order):
            raise BriefError("BRIEF_RELATION_SCOPE_INVALID")
        return sorted(values, key=order.__getitem__)


class BriefRunner:
    def __init__(
        self, repository: BriefRepository, client: BriefClient, *, max_attempts: int
    ) -> None:
        self.repository = repository
        self.client = client
        self.max_attempts = max_attempts

    async def run_user(self, user_id: UUID) -> BriefRun:
        value = await self.repository.input_snapshot(user_id)
        run = await self.repository.create_or_reuse(value, max_attempts=self.max_attempts)
        if run.status in {"completed", "failed"}:
            return run
        run = await self.repository.start_attempt(run.id)
        try:
            response = None if not value.events else await self.client.generate_brief(value)
            return await self.repository.persist_success(run.id, value, response)
        except (AnalysisError, BriefError, SQLAlchemyError) as error:
            retryable = getattr(
                error,
                "retryable",
                isinstance(error, (AnalysisError, SQLAlchemyError)),
            )
            return await self.repository.persist_failure(
                run.id,
                getattr(error, "error_code", "BRIEF_FAILED"),
                retryable=retryable,
            )
