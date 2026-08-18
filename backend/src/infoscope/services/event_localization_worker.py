from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.localization_schemas import (
    OUTPUT_SCHEMA_VERSION,
    EventLocalizationInput,
    EventLocalizationItem,
    EventLocalizationPayload,
    EventLocalizationResponse,
    canonical_hash,
    validate_localization_output,
)
from infoscope.models import (
    Event,
    EventLocalization,
    EventLocalizationArtifact,
    EventLocalizationBatch,
    EventLocalizationRun,
    User,
)
from infoscope.services.event_localization import event_localization_item


class EventLocalizationError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class LocalizationClient(Protocol):
    async def localize(self, value: EventLocalizationInput) -> EventLocalizationResponse: ...


def collection_hash(items: Sequence[EventLocalizationItem]) -> str:
    payload = json.dumps(
        [item.model_dump(mode="json") for item in items],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class EventLocalizationRepository:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self.database = database
        self.clock = clock
        self.stale_after = stale_after

    async def snapshot(self, *, lock: bool = False) -> list[EventLocalizationItem]:
        query = select(Event).order_by(Event.id)
        if lock:
            query = query.with_for_update()
        events = list((await self.database.execute(query)).scalars())
        return [event_localization_item(event) for event in events]

    async def create_or_reuse(
        self,
        *,
        provider: str,
        model: str,
        batch_size: int,
        batch_concurrency: int,
        max_attempts: int,
    ) -> EventLocalizationRun:
        if not 1 <= batch_size <= 10 or not 1 <= batch_concurrency <= 3 or max_attempts <= 0:
            raise ValueError("invalid localization runner bounds")
        await self.database.execute(text("SELECT pg_advisory_xact_lock(1768392481)"))
        active = (
            await self.database.execute(
                select(EventLocalizationRun)
                .where(
                    EventLocalizationRun.locale == "zh-CN", EventLocalizationRun.active_slot == 1
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if active is not None:
            await self.database.commit()
            return active
        items = await self.snapshot(lock=True)
        input_hash = collection_hash(items)
        completed = (
            await self.database.execute(
                select(EventLocalizationRun)
                .where(
                    EventLocalizationRun.locale == "zh-CN",
                    EventLocalizationRun.input_hash == input_hash,
                    EventLocalizationRun.status == "completed",
                )
                .order_by(EventLocalizationRun.finished_at.desc(), EventLocalizationRun.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if completed is not None:
            current_count = (
                await self.database.execute(
                    select(func.count(EventLocalization.id)).where(
                        EventLocalization.locale == "zh-CN",
                        EventLocalization.event_id.in_([item.event_id for item in items]),
                        EventLocalization.event_input_hash.in_(
                            [canonical_hash(item) for item in items]
                        ),
                    )
                )
            ).scalar_one()
            if current_count == len(items):
                await self.database.commit()
                return completed
        batches = [items[index : index + batch_size] for index in range(0, len(items), batch_size)]
        run = EventLocalizationRun(
            locale="zh-CN",
            input_hash=input_hash,
            status="pending" if batches else "completed",
            active_slot=1 if batches else None,
            provider=provider,
            model=model,
            batch_size=batch_size,
            batch_concurrency=batch_concurrency,
            total_event_count=len(items),
            batch_count=len(batches),
            completed_batch_count=0,
            failed_batch_count=0,
            token_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            if not batches
            else None,
            finished_at=datetime.now(UTC) if not batches else None,
        )
        self.database.add(run)
        await self.database.flush()
        self.database.add_all(
            [
                EventLocalizationBatch(
                    run_id=run.id,
                    batch_index=index,
                    event_ids=[item.event_id for item in batch],
                    input_hash=canonical_hash(EventLocalizationInput(events=batch)),
                    status="pending",
                    max_attempts=max_attempts,
                )
                for index, batch in enumerate(batches)
            ]
        )
        await self.database.commit()
        return run

    async def start_run(self, run_id: UUID) -> EventLocalizationRun:
        run = await self._run(run_id, lock=True)
        if run.status == "pending":
            run.status = "running"
            run.started_at = datetime.now(UTC)
        await self.database.commit()
        return run

    async def runnable_batch_ids(self, run_id: UUID) -> list[UUID]:
        stale_cutoff = self.clock() - self.stale_after
        return list(
            (
                await self.database.execute(
                    select(EventLocalizationBatch.id)
                    .where(
                        EventLocalizationBatch.run_id == run_id,
                        EventLocalizationBatch.attempt_count < EventLocalizationBatch.max_attempts,
                        or_(
                            EventLocalizationBatch.status.in_(["pending", "failed"]),
                            and_(
                                EventLocalizationBatch.status == "running",
                                EventLocalizationBatch.updated_at < stale_cutoff,
                            ),
                        ),
                    )
                    .order_by(EventLocalizationBatch.batch_index)
                )
            ).scalars()
        )

    async def localization_needed(self) -> bool:
        active = (
            await self.database.execute(
                select(EventLocalizationRun.id)
                .where(
                    EventLocalizationRun.locale == "zh-CN",
                    EventLocalizationRun.active_slot == 1,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active is not None:
            return True
        items = await self.snapshot()
        if not items:
            return False
        count = (
            await self.database.execute(
                select(func.count(EventLocalization.id)).where(
                    EventLocalization.locale == "zh-CN",
                    EventLocalization.event_id.in_([item.event_id for item in items]),
                    EventLocalization.event_input_hash.in_(
                        [canonical_hash(item) for item in items]
                    ),
                )
            )
        ).scalar_one()
        return count != len(items)

    async def claim_batch(
        self, batch_id: UUID
    ) -> tuple[EventLocalizationBatch, EventLocalizationInput]:
        batch = (
            await self.database.execute(
                select(EventLocalizationBatch)
                .where(EventLocalizationBatch.id == batch_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if batch is None or batch.status == "completed":
            raise EventLocalizationError("EVENT_LOCALIZATION_BATCH_NOT_RUNNABLE")
        if (
            batch.status == "running"
            and batch.updated_at >= self.clock() - self.stale_after
        ):
            raise EventLocalizationError("EVENT_LOCALIZATION_BATCH_NOT_RUNNABLE")
        if batch.attempt_count >= batch.max_attempts:
            raise EventLocalizationError("EVENT_LOCALIZATION_MAX_ATTEMPTS_REACHED")
        value = await self._batch_input(batch.event_ids, lock=False)
        batch.status = "running"
        batch.attempt_count += 1
        batch.started_at = batch.started_at or datetime.now(UTC)
        batch.finished_at = None
        batch.error_code = None
        await self.database.commit()
        return batch, value

    async def reusable_artifact(self, input_hash: str) -> EventLocalizationArtifact | None:
        return (
            await self.database.execute(
                select(EventLocalizationArtifact).where(
                    EventLocalizationArtifact.locale == "zh-CN",
                    EventLocalizationArtifact.input_hash == input_hash,
                )
            )
        ).scalar_one_or_none()

    async def persist_success(
        self,
        batch_id: UUID,
        original: EventLocalizationInput,
        response: EventLocalizationResponse,
        *,
        reusable_artifact_id: UUID | None = None,
    ) -> None:
        await self.database.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        batch = (
            await self.database.execute(
                select(EventLocalizationBatch)
                .where(EventLocalizationBatch.id == batch_id)
                .with_for_update()
            )
        ).scalar_one()
        if batch.status != "running" or batch.input_hash != canonical_hash(original):
            raise EventLocalizationError("EVENT_LOCALIZATION_BATCH_STATE_INVALID")
        current = await self._batch_input(batch.event_ids, lock=True)
        if current != original or canonical_hash(current) != batch.input_hash:
            raise EventLocalizationError("EVENT_LOCALIZATION_INPUT_CHANGED")
        try:
            validate_localization_output(current, response.payload)
        except ValueError as error:
            error_codes = {
                "localization output changed URLs": "EVENT_LOCALIZATION_URL_CHANGED",
                "localization output changed numeric tokens": "EVENT_LOCALIZATION_NUMBERS_CHANGED",
            }
            raise EventLocalizationError(
                error_codes.get(str(error), "EVENT_LOCALIZATION_OUTPUT_INVALID")
            ) from error
        artifact = (
            await self.database.get(EventLocalizationArtifact, reusable_artifact_id)
            if reusable_artifact_id is not None
            else None
        )
        if artifact is None:
            artifact = EventLocalizationArtifact(
                locale="zh-CN",
                schema_version=OUTPUT_SCHEMA_VERSION,
                input_hash=batch.input_hash,
                output_payload=response.payload.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
            self.database.add(artifact)
            await self.database.flush()
        for source, decision in zip(current.events, response.payload.decisions, strict=True):
            await self.database.execute(
                insert(EventLocalization)
                .values(
                    event_id=source.event_id,
                    locale="zh-CN",
                    source_artifact_id=artifact.id,
                    event_input_hash=canonical_hash(source),
                    title=decision.title,
                    overview=decision.overview,
                )
                .on_conflict_do_update(
                    constraint="uq_event_localizations_event_locale",
                    set_={
                        "source_artifact_id": artifact.id,
                        "event_input_hash": canonical_hash(source),
                        "title": decision.title,
                        "overview": decision.overview,
                        "updated_at": func.now(),
                    },
                )
            )
        batch.status = "completed"
        batch.artifact_id = artifact.id
        batch.artifact_reused = reusable_artifact_id is not None
        batch.token_usage = (
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            if reusable_artifact_id is not None
            else response.token_usage.model_dump(mode="json")
        )
        batch.error_code = None
        batch.finished_at = datetime.now(UTC)
        await self.database.commit()

    async def fail_batch(self, batch_id: UUID, error_code: str) -> None:
        batch = (
            await self.database.execute(
                select(EventLocalizationBatch)
                .where(EventLocalizationBatch.id == batch_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if batch is not None and batch.status == "running":
            batch.status = "failed"
            batch.error_code = error_code
            batch.finished_at = datetime.now(UTC)
        await self.database.commit()

    async def refresh_run(self, run_id: UUID) -> EventLocalizationRun:
        run = await self._run(run_id, lock=True)
        batches = list(
            (
                await self.database.execute(
                    select(EventLocalizationBatch)
                    .where(EventLocalizationBatch.run_id == run.id)
                    .order_by(EventLocalizationBatch.batch_index)
                )
            ).scalars()
        )
        run.completed_batch_count = sum(item.status == "completed" for item in batches)
        run.failed_batch_count = sum(item.status == "failed" for item in batches)
        terminal = [
            item
            for item in batches
            if item.status == "failed" and item.attempt_count >= item.max_attempts
        ]
        if run.completed_batch_count == run.batch_count:
            run.status = "completed"
            run.active_slot = None
            run.error_code = None
            run.finished_at = datetime.now(UTC)
            usages = [item.token_usage or {} for item in batches]
            run.token_usage = {
                key: sum(int(value.get(key, 0)) for value in usages)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
            await self.database.execute(
                update(User)
                .where(User.onboarding_completed.is_(True))
                .values(personalization_update_requested_at=func.now())
            )
        elif terminal:
            run.status = "failed"
            run.active_slot = None
            run.error_code = terminal[0].error_code or "EVENT_LOCALIZATION_BATCH_FAILED"
            run.finished_at = datetime.now(UTC)
        await self.database.commit()
        return run

    async def _batch_input(self, event_ids: list[UUID], *, lock: bool) -> EventLocalizationInput:
        query = select(Event).where(Event.id.in_(event_ids)).order_by(Event.id)
        if lock:
            query = query.with_for_update()
        events = list((await self.database.execute(query)).scalars())
        if [event.id for event in events] != event_ids:
            raise EventLocalizationError("EVENT_LOCALIZATION_EVENT_SET_CHANGED")
        try:
            return EventLocalizationInput(
                events=[event_localization_item(event) for event in events]
            )
        except ValidationError as error:
            raise EventLocalizationError("EVENT_LOCALIZATION_INPUT_INVALID") from error

    async def _run(self, run_id: UUID, *, lock: bool) -> EventLocalizationRun:
        query = select(EventLocalizationRun).where(EventLocalizationRun.id == run_id)
        if lock:
            query = query.with_for_update()
        run = (await self.database.execute(query)).scalar_one_or_none()
        if run is None:
            raise EventLocalizationError("EVENT_LOCALIZATION_RUN_NOT_FOUND")
        return run


class EventLocalizationRunner:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        client: LocalizationClient,
        *,
        provider: str,
        model: str,
        batch_size: int,
        batch_concurrency: int,
        max_attempts: int,
    ) -> None:
        self.factory = factory
        self.client = client
        self.provider = provider
        self.model = model
        self.batch_size = batch_size
        self.batch_concurrency = batch_concurrency
        self.max_attempts = max_attempts

    async def run(self) -> EventLocalizationRun:
        async with self.factory() as database:
            repository = EventLocalizationRepository(database)
            run = await repository.create_or_reuse(
                provider=self.provider,
                model=self.model,
                batch_size=self.batch_size,
                batch_concurrency=self.batch_concurrency,
                max_attempts=self.max_attempts,
            )
            if run.status in {"completed", "failed"}:
                return run
            run = await repository.start_run(run.id)
        semaphore = asyncio.Semaphore(self.batch_concurrency)
        while True:
            async with self.factory() as database:
                batch_ids = await EventLocalizationRepository(database).runnable_batch_ids(run.id)
            if not batch_ids:
                break

            async def process(batch_id: UUID) -> None:
                async with semaphore:
                    await self._process_batch(batch_id)

            await asyncio.gather(*(process(batch_id) for batch_id in batch_ids))
            async with self.factory() as database:
                run = await EventLocalizationRepository(database).refresh_run(run.id)
            if run.status in {"completed", "failed"}:
                return run
        async with self.factory() as database:
            return await EventLocalizationRepository(database).refresh_run(run.id)

    async def _process_batch(self, batch_id: UUID) -> None:
        claimed = False
        try:
            async with self.factory() as database:
                repository = EventLocalizationRepository(database)
                batch, value = await repository.claim_batch(batch_id)
                claimed = True
                artifact = await repository.reusable_artifact(batch.input_hash)
            if artifact is None:
                response = await self.client.localize(value)
                artifact_id = None
            else:
                response = EventLocalizationResponse(
                    payload=EventLocalizationPayload.model_validate(artifact.output_payload),
                    provider=artifact.provider,
                    model=artifact.model,
                    token_usage=artifact.token_usage,
                )
                artifact_id = artifact.id
            await self._persist_success_with_retry(
                batch_id,
                value,
                response,
                reusable_artifact_id=artifact_id,
            )
        except (AnalysisError, EventLocalizationError, ValidationError, ValueError) as error:
            error_code = getattr(error, "error_code", "EVENT_LOCALIZATION_OUTPUT_INVALID")
            if not claimed and error_code == "EVENT_LOCALIZATION_BATCH_NOT_RUNNABLE":
                return
            async with self.factory() as database:
                await EventLocalizationRepository(database).fail_batch(batch_id, error_code)

    async def _persist_success_with_retry(
        self,
        batch_id: UUID,
        value: EventLocalizationInput,
        response: EventLocalizationResponse,
        *,
        reusable_artifact_id: UUID | None,
    ) -> None:
        for attempt in range(3):
            try:
                async with self.factory() as database:
                    await EventLocalizationRepository(database).persist_success(
                        batch_id,
                        value,
                        response,
                        reusable_artifact_id=reusable_artifact_id,
                    )
                return
            except DBAPIError as error:
                sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
                    getattr(error.orig, "__cause__", None), "sqlstate", None
                )
                if sqlstate != "40001":
                    raise
                if attempt == 2:
                    raise EventLocalizationError(
                        "EVENT_LOCALIZATION_SERIALIZATION_RETRY_EXHAUSTED"
                    ) from error
                await asyncio.sleep(0)
