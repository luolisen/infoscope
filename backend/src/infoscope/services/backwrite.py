from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.ask_schemas import (
    AskBaseAnalysisInput,
    AskEventInput,
    AskReconciliationSignal,
)
from infoscope.analysis.backwrite_schemas import (
    BackwriteDownstreamRefresh,
    BackwriteReconciliationArtifactPayload,
    BackwriteReconciliationInput,
    BackwriteReconciliationPayload,
    BackwriteReconciliationResponse,
    BackwriteResearchArtifactPayload,
    BackwriteResearchResult,
    BackwriteSnapshotPayload,
    BackwriteSnapshotSpec,
    backwrite_reconciliation_input_hash,
    backwrite_snapshot_hash,
)
from infoscope.analysis.client import AnalysisError
from infoscope.analysis.intelligence_schemas import (
    BaseAnalysisResponse,
    ClaimExtractionResponse,
    ConflictAnalysisResponse,
    EventBaseAnalysisInput,
    EventClaimInput,
    EventConflictInput,
    EventTimelineInput,
    ExistingBaseAnalysisCandidate,
    ExistingClaimCandidate,
    ExistingConflictCandidate,
    ExistingTimelineCandidate,
    TimelineReconstructionResponse,
)
from infoscope.integrations.research.schemas import ResearchRequestSpec
from infoscope.models import (
    BackwriteCycle,
    BackwriteItem,
    BackwriteReconciliationArtifact,
    BackwriteReconciliationRun,
    BackwriteResearchArtifact,
    BaseAnalysis,
    Claim,
    ClaimSignal,
    Conflict,
    ConflictClaim,
    ConflictSignal,
    Event,
    EventSignal,
    NormalizationStatus,
    RawInformation,
    ResearchRequest,
    ResearchSource,
    ResearchSourceKind,
    ResearchSourceStatus,
    ResearchStatus,
    ResearchTrigger,
    Signal,
    TimelineClaim,
    TimelineEntry,
    User,
)
from infoscope.services.acquisition import AcquisitionRepository
from infoscope.services.base_analysis import BaseAnalysisRepository, BaseAnalysisRunner
from infoscope.services.claims_timeline import (
    ClaimExtractionRunner,
    ConflictAnalysisRunner,
    IntelligenceError,
    IntelligenceRepository,
    TimelineReconstructionRunner,
)
from infoscope.services.normalization import DeterministicNormalizer, NormalizationError
from infoscope.services.research import ResearchError, ResearchRepository, ResearchRunner

logger = logging.getLogger("infoscope.backwrite")

BACKWRITE_RESEARCH_NAMESPACE = UUID("23df92fd-9cd3-4bdd-8d98-0db4f79be76a")
BACKWRITE_RESEARCH_QUESTION = (
    "What material, verifiable developments, corrections, or missing context have emerged "
    "for this Event since its current display_time?"
)


class BackwriteError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool = False) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


class BackwriteClient(Protocol):
    async def reconcile_backwrite_event(
        self, value: BackwriteReconciliationInput
    ) -> BackwriteReconciliationResponse: ...

    async def extract_claims(
        self, *, events: list[EventClaimInput], candidates: list[ExistingClaimCandidate]
    ) -> ClaimExtractionResponse: ...

    async def reconstruct_timeline(
        self, *, events: list[EventTimelineInput], candidates: list[ExistingTimelineCandidate]
    ) -> TimelineReconstructionResponse: ...

    async def analyze_conflicts(
        self, *, events: list[EventConflictInput], candidates: list[ExistingConflictCandidate]
    ) -> ConflictAnalysisResponse: ...

    async def analyze_base(
        self,
        *,
        events: list[EventBaseAnalysisInput],
        candidates: list[ExistingBaseAnalysisCandidate],
    ) -> BaseAnalysisResponse: ...


class UserVisibleEventSnapshotProvider(Protocol):
    async def ordered_event_ids(self, user_id: UUID) -> list[UUID]: ...

    async def is_visible(self, user_id: UUID, event_id: UUID) -> bool: ...


class UnavailableUserVisibleEventSnapshotProvider:
    async def ordered_event_ids(self, user_id: UUID) -> list[UUID]:
        _ = user_id
        raise BackwriteError("BACKWRITE_VISIBILITY_PROVIDER_UNAVAILABLE")

    async def is_visible(self, user_id: UUID, event_id: UUID) -> bool:
        _ = (user_id, event_id)
        raise BackwriteError("BACKWRITE_VISIBILITY_PROVIDER_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class PreparedBackwriteItem:
    cycle: BackwriteCycle
    item: BackwriteItem
    run: BackwriteReconciliationRun
    cycle_id: UUID = field(init=False)
    item_id: UUID = field(init=False)
    event_id: UUID = field(init=False)
    run_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        # A rollback expires ORM instances. Freeze identifiers while the
        # claimed rows are loaded so audit paths never lazy-load expired state.
        object.__setattr__(self, "cycle_id", self.cycle.id)
        object.__setattr__(self, "item_id", self.item.id)
        object.__setattr__(self, "event_id", self.item.event_id)
        object.__setattr__(self, "run_id", self.run.id)


def frozen_queue_indices(size: int) -> list[int]:
    if size < 0:
        raise ValueError("queue size must not be negative")
    order: list[int] = []
    left = 0
    right = size - 1
    while left <= right:
        order.append(left)
        if left != right:
            order.append(right)
        left += 1
        right -= 1
    return order


class BackwriteRepository:
    def __init__(
        self,
        database: AsyncSession,
        *,
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self.database = database
        self.stale_after = stale_after

    async def create_or_reuse_cycle(
        self,
        spec: BackwriteSnapshotSpec,
        *,
        provider: UserVisibleEventSnapshotProvider,
        max_attempts: int,
    ) -> tuple[BackwriteCycle, bool]:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        user = await self.database.get(User, spec.user_id)
        if user is None:
            raise BackwriteError("BACKWRITE_USER_NOT_FOUND")
        ordered_event_ids = await provider.ordered_event_ids(spec.user_id)
        if len(ordered_event_ids) != len(set(ordered_event_ids)):
            raise BackwriteError("BACKWRITE_VISIBILITY_SNAPSHOT_INVALID")
        for event_id in ordered_event_ids:
            if not await provider.is_visible(spec.user_id, event_id):
                raise BackwriteError("BACKWRITE_EVENT_NOT_VISIBLE")
        snapshot = BackwriteSnapshotPayload(
            user_id=spec.user_id,
            ordered_event_ids=ordered_event_ids,
        )
        input_hash = backwrite_snapshot_hash(snapshot)
        if ordered_event_ids:
            event_ids = set(
                (
                    await self.database.execute(
                        select(Event.id).where(Event.id.in_(ordered_event_ids))
                    )
                ).scalars()
            )
            if event_ids != set(ordered_event_ids):
                raise BackwriteError("BACKWRITE_EVENT_NOT_FOUND")
        cycle_id = UUID(int=0)
        result = await self.database.execute(
            insert(BackwriteCycle)
            .values(
                user_id=spec.user_id,
                idempotency_key=spec.idempotency_key,
                input_hash=input_hash,
                schema_version=snapshot.schema_version,
                status="completed" if not ordered_event_ids else "pending",
                snapshot_payload=snapshot.model_dump(mode="json"),
                item_count=len(ordered_event_ids),
                finished_at=datetime.now(UTC) if not ordered_event_ids else None,
            )
            .on_conflict_do_nothing(index_elements=[BackwriteCycle.idempotency_key])
            .returning(BackwriteCycle.id)
        )
        inserted_id = result.scalar_one_or_none()
        inserted = inserted_id is not None
        if inserted:
            cycle_id = inserted_id
            queue = frozen_queue_indices(len(ordered_event_ids))
            queue_position = {
                snapshot_position: index for index, snapshot_position in enumerate(queue)
            }
            self.database.add_all(
                [
                    BackwriteItem(
                        cycle_id=cycle_id,
                        event_id=event_id,
                        snapshot_position=snapshot_position,
                        queue_position=queue_position[snapshot_position],
                        max_attempts=max_attempts,
                    )
                    for snapshot_position, event_id in enumerate(ordered_event_ids)
                ]
            )
        cycle = (
            await self.database.execute(
                select(BackwriteCycle).where(
                    BackwriteCycle.id
                    == (
                        cycle_id
                        if inserted
                        else select(BackwriteCycle.id)
                        .where(BackwriteCycle.idempotency_key == spec.idempotency_key)
                        .scalar_subquery()
                    )
                )
            )
        ).scalar_one()
        if cycle.input_hash != input_hash:
            await self.database.rollback()
            raise BackwriteError("BACKWRITE_IDEMPOTENCY_CONFLICT")
        await self.database.commit()
        return cycle, inserted

    async def prepare_next_item(self, cycle_id: UUID) -> PreparedBackwriteItem | None:
        await self.recover_stale_items(cycle_id)
        cycle = (
            await self.database.execute(
                select(BackwriteCycle).where(BackwriteCycle.id == cycle_id).with_for_update()
            )
        ).scalar_one_or_none()
        if cycle is None:
            raise BackwriteError("BACKWRITE_CYCLE_NOT_FOUND")
        if cycle.status in {"completed", "partial", "failed"}:
            await self.database.commit()
            return None
        terminal_failure = await self.database.scalar(
            select(BackwriteItem.id)
            .where(
                BackwriteItem.cycle_id == cycle.id,
                BackwriteItem.status == "failed",
            )
            .limit(1)
        )
        if terminal_failure is not None:
            await self._abort_pending_items(cycle)
            await self._finalize_cycle(cycle)
            await self.database.commit()
            return None
        item = (
            await self.database.execute(
                select(BackwriteItem)
                .where(
                    BackwriteItem.cycle_id == cycle.id,
                    BackwriteItem.status == "pending",
                    BackwriteItem.attempt_count < BackwriteItem.max_attempts,
                )
                .order_by(BackwriteItem.queue_position)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if item is None:
            await self._finalize_cycle(cycle)
            await self.database.commit()
            return None
        now = datetime.now(UTC)
        item.attempt_count += 1
        item.status = "researching"
        item.error_code = None
        item.started_at = item.started_at or now
        item.finished_at = None
        cycle.status = "running"
        cycle.started_at = cycle.started_at or now
        run = BackwriteReconciliationRun(
            item_id=item.id,
            attempt=item.attempt_count,
            status="running",
            started_at=now,
        )
        self.database.add(run)
        await self.database.commit()
        return PreparedBackwriteItem(cycle, item, run)

    async def _abort_pending_items(self, cycle: BackwriteCycle) -> None:
        """Stop a queue that can no longer produce a successful cycle."""
        pending = list(
            (
                await self.database.execute(
                    select(BackwriteItem)
                    .where(
                        BackwriteItem.cycle_id == cycle.id,
                        BackwriteItem.status == "pending",
                    )
                    .order_by(BackwriteItem.queue_position)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        finished = datetime.now(UTC)
        for item in pending:
            item.status = "failed"
            item.outcome = None
            item.error_code = "BACKWRITE_CYCLE_ABORTED"
            item.finished_at = finished

    async def recover_stale_items(self, cycle_id: UUID) -> list[BackwriteItem]:
        """Fail-closed items abandoned by a lost worker and make retries durable.

        A worker can disappear after claiming an item but before its exception
        handler gets a chance to audit it.  Without this recovery, the cycle
        remains permanently active in ``researching``/``reconciling`` and no
        later worker can claim the queue.  Recovery only touches items whose
        ``updated_at`` is older than the configured lease and records a
        dedicated stable error on their reconciliation run.
        """
        cutoff = datetime.now(UTC) - self.stale_after
        stale = list(
            (
                await self.database.execute(
                    select(BackwriteItem)
                    .where(
                        BackwriteItem.cycle_id == cycle_id,
                        BackwriteItem.status.in_(("researching", "reconciling")),
                        BackwriteItem.updated_at < cutoff,
                    )
                    .order_by(BackwriteItem.queue_position)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        if not stale:
            return []
        finished = datetime.now(UTC)
        for item in stale:
            run = (
                await self.database.execute(
                    select(BackwriteReconciliationRun)
                    .where(
                        BackwriteReconciliationRun.item_id == item.id,
                        BackwriteReconciliationRun.attempt == item.attempt_count,
                        BackwriteReconciliationRun.status == "running",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if run is not None:
                run.status = "failed"
                run.error_code = "BACKWRITE_WORKER_LOST"
                run.finished_at = finished
            item.error_code = "BACKWRITE_WORKER_LOST"
            if item.attempt_count < item.max_attempts:
                item.status = "pending"
                item.finished_at = None
            else:
                item.status = "failed"
                item.finished_at = finished
        cycle = await self.database.get(BackwriteCycle, cycle_id)
        if cycle is None:
            raise BackwriteError("BACKWRITE_CYCLE_NOT_FOUND")
        await self.database.flush()
        await self._finalize_cycle(cycle)
        await self.database.commit()
        return stale

    async def fail_abandoned_cycles(
        self,
        idempotency_keys: set[UUID],
        *,
        error_code: str = "BACKWRITE_MAINTENANCE_LOST",
    ) -> list[BackwriteCycle]:
        """Terminalize active cycles whose owning Maintenance run is already terminal.

        Maintenance owns its Backwrite cycle through a deterministic idempotency key. If the
        worker disappears, the Maintenance lease is recovered independently; without this repair
        the cycle and its frozen queue remain permanently ``running`` with no runner that can
        legally resume them.  Completed and already-failed items remain immutable, while every
        unfinished item receives an auditable fail-closed terminal state.
        """
        if not idempotency_keys:
            return []
        cycles = list(
            (
                await self.database.execute(
                    select(BackwriteCycle)
                    .where(
                        BackwriteCycle.idempotency_key.in_(idempotency_keys),
                        BackwriteCycle.status.in_(("pending", "running")),
                    )
                    .order_by(BackwriteCycle.created_at, BackwriteCycle.id)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        if not cycles:
            return []
        finished = datetime.now(UTC)
        for cycle in cycles:
            items = list(
                (
                    await self.database.execute(
                        select(BackwriteItem)
                        .where(
                            BackwriteItem.cycle_id == cycle.id,
                            BackwriteItem.status.in_(("pending", "researching", "reconciling")),
                        )
                        .order_by(BackwriteItem.queue_position)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            item_ids = [item.id for item in items]
            if item_ids:
                runs = list(
                    (
                        await self.database.execute(
                            select(BackwriteReconciliationRun)
                            .where(
                                BackwriteReconciliationRun.item_id.in_(item_ids),
                                BackwriteReconciliationRun.status == "running",
                            )
                            .with_for_update(skip_locked=True)
                        )
                    ).scalars()
                )
                for run in runs:
                    run.status = "failed"
                    run.error_code = error_code
                    run.finished_at = finished
            for item in items:
                item.status = "failed"
                item.outcome = None
                item.error_code = error_code
                item.finished_at = finished
            await self.database.flush()
            await self._finalize_cycle(cycle)
        return cycles

    async def attach_research_request(self, item_id: UUID, request_id: UUID) -> None:
        item = await self.database.get(BackwriteItem, item_id)
        if item is None:
            raise BackwriteError("BACKWRITE_ITEM_NOT_FOUND")
        if item.research_request_id not in {None, request_id}:
            raise BackwriteError("BACKWRITE_RESEARCH_REQUEST_MISMATCH")
        item.research_request_id = request_id
        await self.database.commit()

    async def successful_sources(self, request_id: UUID) -> list[ResearchSource]:
        return list(
            (
                await self.database.execute(
                    select(ResearchSource)
                    .where(
                        ResearchSource.research_request_id == request_id,
                        ResearchSource.status == ResearchSourceStatus.SUCCEEDED.value,
                        ResearchSource.raw_information_id.is_not(None),
                    )
                    .order_by(ResearchSource.candidate_index)
                )
            ).scalars()
        )

    async def input_snapshot(self, item_id: UUID) -> BackwriteReconciliationInput:
        item = await self.database.get(BackwriteItem, item_id)
        if item is None or item.source_artifact_id is None:
            raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_MISSING")
        source = await self.database.get(BackwriteResearchArtifact, item.source_artifact_id)
        if source is None or source.item_id != item.id:
            raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_INVALID")
        try:
            source_payload = BackwriteResearchArtifactPayload.model_validate(source.payload)
        except ValueError as error:
            raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_INVALID") from error
        if source_payload.item_id != item.id or source_payload.event_id != item.event_id:
            raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_INVALID")
        event = await self._event_input(item.event_id)
        signals = await self._canonical_signals(source_payload)
        return BackwriteReconciliationInput(
            item_id=item.id,
            event_id=item.event_id,
            event=event,
            canonical_signals=signals,
        )

    async def persist_research_artifact(
        self,
        prepared: PreparedBackwriteItem,
        *,
        request: ResearchRequest,
        results: list[BackwriteResearchResult],
    ) -> BackwriteResearchArtifact:
        if request.status not in {ResearchStatus.SUCCEEDED.value, ResearchStatus.PARTIAL.value}:
            raise BackwriteError("BACKWRITE_RESEARCH_FAILED")
        payload = BackwriteResearchArtifactPayload(
            item_id=prepared.item_id,
            event_id=prepared.event_id,
            research_request_id=request.id,
            research_status=request.status,
            results=results,
        )
        artifact = (
            await self.database.execute(
                select(BackwriteResearchArtifact).where(
                    BackwriteResearchArtifact.item_id == prepared.item_id
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            artifact = BackwriteResearchArtifact(
                item_id=prepared.item_id,
                research_request_id=request.id,
                schema_version=payload.schema_version,
                payload=payload.model_dump(mode="json"),
            )
            self.database.add(artifact)
            await self.database.flush()
        else:
            try:
                existing = BackwriteResearchArtifactPayload.model_validate(artifact.payload)
            except ValueError as error:
                raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_INVALID") from error
            if existing != payload or artifact.research_request_id != request.id:
                raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_CONFLICT")
        item = await self.database.get(BackwriteItem, prepared.item_id)
        if item is None:
            raise BackwriteError("BACKWRITE_ITEM_NOT_FOUND")
        if item.source_artifact_id not in {None, artifact.id}:
            raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_CONFLICT")
        item.source_artifact_id = artifact.id
        await self.database.commit()
        return artifact

    async def store_input_hash(self, item_id: UUID, value: BackwriteReconciliationInput) -> str:
        input_hash = backwrite_reconciliation_input_hash(value)
        item = await self.database.get(BackwriteItem, item_id)
        if item is None:
            raise BackwriteError("BACKWRITE_ITEM_NOT_FOUND")
        if item.input_hash is None:
            item.input_hash = input_hash
            item.status = "reconciling"
            await self.database.commit()
        elif item.input_hash != input_hash:
            raise BackwriteError("BACKWRITE_INPUT_CHANGED")
        return input_hash

    async def persist_no_change(
        self,
        prepared: PreparedBackwriteItem,
        value: BackwriteReconciliationInput,
    ) -> BackwriteItem:
        output = BackwriteReconciliationPayload(
            item_id=prepared.item_id,
            event_id=prepared.event_id,
            decision="no_change",
            event_update=None,
            unassigned_signal_ids=[],
            rationale="Research produced no usable canonical Signals.",
        )
        return await self._persist(
            prepared,
            original_input=value,
            output=output,
            response=None,
            artifact_kind="deterministic_no_change",
        )

    async def persist_success(
        self,
        prepared: PreparedBackwriteItem,
        *,
        original_input: BackwriteReconciliationInput,
        response: BackwriteReconciliationResponse,
        client: BackwriteClient,
    ) -> BackwriteItem:
        return await self._persist(
            prepared,
            original_input=original_input,
            output=response.payload,
            response=response,
            artifact_kind="model",
            client=client,
        )

    async def _persist(
        self,
        prepared: PreparedBackwriteItem,
        *,
        original_input: BackwriteReconciliationInput,
        output: BackwriteReconciliationPayload,
        response: BackwriteReconciliationResponse | None,
        artifact_kind: str,
        client: BackwriteClient | None = None,
    ) -> BackwriteItem:
        await self.database.rollback()
        item = (
            await self.database.execute(
                select(BackwriteItem)
                .where(BackwriteItem.id == prepared.item_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        run = (
            await self.database.execute(
                select(BackwriteReconciliationRun)
                .where(BackwriteReconciliationRun.id == prepared.run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        await self._lock_input(original_input)
        current = await self.input_snapshot(item.id)
        current_hash = backwrite_reconciliation_input_hash(current)
        if current_hash != item.input_hash:
            raise BackwriteError("BACKWRITE_INPUT_CHANGED")
        self.validate_output(output, current)
        newly_attached: list[UUID] = []
        downstream_refresh: BackwriteDownstreamRefresh | None = None
        if output.event_update is not None:
            event = await self.database.get(Event, item.event_id)
            if event is None:
                raise BackwriteError("BACKWRITE_INPUT_CHANGED")
            event.title = output.event_update.title
            event.overview = output.event_update.overview
            event.display_time = output.event_update.display_time
            existing = set(
                (
                    await self.database.execute(
                        select(EventSignal.signal_id).where(EventSignal.event_id == event.id)
                    )
                ).scalars()
            )
            newly_attached = [
                signal_id
                for signal_id in output.event_update.signal_ids
                if signal_id not in existing
            ]
            if newly_attached:
                await self.database.execute(
                    insert(EventSignal)
                    .values(
                        [
                            {
                                "event_id": event.id,
                                "signal_id": signal_id,
                                "attached_by_pipeline_run_id": None,
                                "attached_by_ask_reconciliation_run_id": None,
                                "attached_by_backwrite_reconciliation_run_id": run.id,
                            }
                            for signal_id in newly_attached
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=[EventSignal.event_id, EventSignal.signal_id]
                    )
                )
            if client is None:
                raise BackwriteError("BACKWRITE_DOWNSTREAM_CLIENT_MISSING")
            await self.database.flush()
            downstream_refresh = await self._refresh_downstream(
                client=client,
                event_id=event.id,
                run_id=run.id,
            )
        if item.research_request_id is None or item.source_artifact_id is None:
            raise BackwriteError("BACKWRITE_RESEARCH_ARTIFACT_MISSING")
        payload = BackwriteReconciliationArtifactPayload(
            item_id=item.id,
            event_id=item.event_id,
            research_request_id=item.research_request_id,
            output=output,
            newly_attached_signal_ids=newly_attached,
            downstream_refresh=downstream_refresh,
        )
        self.database.add(
            BackwriteReconciliationArtifact(
                item_id=item.id,
                created_by_run_id=run.id,
                research_request_id=item.research_request_id,
                source_artifact_id=item.source_artifact_id,
                artifact_kind=artifact_kind,
                schema_version=payload.schema_version,
                input_hash=current_hash,
                payload=payload.model_dump(mode="json"),
                provider=response.provider if response is not None else None,
                model=response.model if response is not None else None,
                token_usage=response.token_usage.model_dump(mode="json")
                if response is not None
                else None,
            )
        )
        finished = datetime.now(UTC)
        run.status = "completed"
        run.error_code = None
        run.finished_at = finished
        item.status = "completed"
        item.outcome = "updated" if output.decision == "update" else "no_change"
        item.error_code = None
        item.finished_at = finished
        cycle = await self.database.get(BackwriteCycle, item.cycle_id)
        if cycle is None:
            raise BackwriteError("BACKWRITE_CYCLE_NOT_FOUND")
        await self.database.flush()
        await self._finalize_cycle(cycle)
        await self.database.commit()
        return item

    async def persist_failure(
        self,
        prepared: PreparedBackwriteItem,
        *,
        error_code: str,
        retryable: bool,
    ) -> None:
        await self.database.rollback()
        item = (
            await self.database.execute(
                select(BackwriteItem).where(BackwriteItem.id == prepared.item_id).with_for_update()
            )
        ).scalar_one()
        run = (
            await self.database.execute(
                select(BackwriteReconciliationRun)
                .where(BackwriteReconciliationRun.id == prepared.run_id)
                .with_for_update()
            )
        ).scalar_one()
        finished = datetime.now(UTC)
        run.status = "failed"
        run.error_code = error_code
        run.finished_at = finished
        item.error_code = error_code
        if retryable and item.attempt_count < item.max_attempts:
            item.status = "pending"
            item.finished_at = None
        else:
            item.status = "failed"
            item.finished_at = finished
        cycle = await self.database.get(BackwriteCycle, item.cycle_id)
        if cycle is None:
            raise BackwriteError("BACKWRITE_CYCLE_NOT_FOUND")
        await self.database.flush()
        await self._finalize_cycle(cycle)
        await self.database.commit()

    async def _refresh_downstream(
        self,
        *,
        client: BackwriteClient,
        event_id: UUID,
        run_id: UUID,
    ) -> BackwriteDownstreamRefresh:
        intelligence = IntelligenceRepository(self.database)

        claim_events, claim_candidates = await intelligence.claim_inputs({event_id})
        claim_response = await client.extract_claims(
            events=claim_events,
            candidates=claim_candidates,
        )
        claim_response = ClaimExtractionRunner._normalize_decisions(
            claim_response,
            claim_events,
            claim_candidates,
        )
        claim_response = ClaimExtractionRunner._normalize_coverage(
            claim_response,
            claim_events,
        )
        ClaimExtractionRunner._validate(
            claim_response.payload,
            claim_events,
            claim_candidates,
        )
        await self._persist_backwrite_claims(
            response=claim_response,
            candidate_ids={item.claim_id for item in claim_candidates},
            run_id=run_id,
        )
        await self.database.flush()

        timeline_events, timeline_candidates = await intelligence.timeline_inputs({event_id})
        timeline_response = await client.reconstruct_timeline(
            events=timeline_events,
            candidates=timeline_candidates,
        )
        timeline_response = TimelineReconstructionRunner._normalize_decisions(
            timeline_response,
            timeline_events,
            timeline_candidates,
        )
        timeline_response = TimelineReconstructionRunner._normalize_coverage(
            timeline_response,
            timeline_events,
        )
        TimelineReconstructionRunner._validate(
            timeline_response.payload,
            timeline_events,
            timeline_candidates,
        )
        await self._persist_backwrite_timeline(
            response=timeline_response,
            candidate_ids={item.timeline_entry_id for item in timeline_candidates},
            run_id=run_id,
        )
        await self.database.flush()

        conflict_events, conflict_candidates = await intelligence.conflict_inputs({event_id})
        conflict_response = await client.analyze_conflicts(
            events=conflict_events,
            candidates=conflict_candidates,
        )
        conflict_response = ConflictAnalysisRunner._normalize_decisions(
            conflict_response,
            conflict_events,
            conflict_candidates,
        )
        conflict_response = ConflictAnalysisRunner._normalize_coverage(
            conflict_response,
            conflict_events,
        )
        ConflictAnalysisRunner._validate(
            conflict_response.payload,
            conflict_events,
            conflict_candidates,
        )
        await self._persist_backwrite_conflicts(
            response=conflict_response,
            candidates={item.conflict_id: item for item in conflict_candidates},
            run_id=run_id,
        )
        await self.database.flush()

        base_repository = BaseAnalysisRepository(self.database)
        base_events, base_candidates = await base_repository.inputs({event_id})
        base_response = await client.analyze_base(
            events=base_events,
            candidates=base_candidates,
        )
        BaseAnalysisRunner._validate(
            base_response.payload,
            base_events,
            base_candidates,
        )
        await self._persist_backwrite_base_analysis(
            response=base_response,
            candidates={item.base_analysis_id: item for item in base_candidates},
            run_id=run_id,
        )
        await self.database.flush()
        return BackwriteDownstreamRefresh(
            claims=claim_response,
            timeline=timeline_response,
            conflicts=conflict_response,
            base_analysis=base_response,
        )

    async def _persist_backwrite_claims(
        self,
        *,
        response: ClaimExtractionResponse,
        candidate_ids: set[UUID],
        run_id: UUID,
    ) -> None:
        for decision in response.payload.new_claims:
            claim = Claim(
                id=uuid4(),
                event_id=decision.event_id,
                text=decision.text,
                state="unresolved",
            )
            self.database.add(claim)
            await self.database.flush()
            await self._attach_backwrite_relations(
                ClaimSignal,
                "claim_id",
                claim.id,
                "signal_id",
                decision.evidence_signal_ids,
                run_id,
                [ClaimSignal.claim_id, ClaimSignal.signal_id],
            )
        for decision in response.payload.existing_claim_updates:
            if decision.existing_claim_id not in candidate_ids:
                raise IntelligenceError("CLAIM_OUTSIDE_CANDIDATES")
            claim = await self.database.get(Claim, decision.existing_claim_id)
            if claim is None or claim.event_id != decision.event_id:
                raise IntelligenceError("CLAIM_EVENT_MISMATCH")
            claim.text = decision.text
            await self._attach_backwrite_relations(
                ClaimSignal,
                "claim_id",
                claim.id,
                "signal_id",
                decision.evidence_signal_ids,
                run_id,
                [ClaimSignal.claim_id, ClaimSignal.signal_id],
            )

    async def _persist_backwrite_timeline(
        self,
        *,
        response: TimelineReconstructionResponse,
        candidate_ids: set[UUID],
        run_id: UUID,
    ) -> None:
        for decision in response.payload.new_entries:
            entry = TimelineEntry(
                id=uuid4(),
                event_id=decision.event_id,
                occurred_at=decision.occurred_at,
                summary=decision.summary,
            )
            self.database.add(entry)
            await self.database.flush()
            await self._attach_backwrite_relations(
                TimelineClaim,
                "timeline_entry_id",
                entry.id,
                "claim_id",
                decision.claim_ids,
                run_id,
                [TimelineClaim.timeline_entry_id, TimelineClaim.claim_id],
            )
        for decision in response.payload.existing_entry_updates:
            if decision.existing_timeline_entry_id not in candidate_ids:
                raise IntelligenceError("TIMELINE_OUTSIDE_CANDIDATES")
            entry = await self.database.get(TimelineEntry, decision.existing_timeline_entry_id)
            if entry is None or entry.event_id != decision.event_id:
                raise IntelligenceError("TIMELINE_EVENT_MISMATCH")
            entry.occurred_at = decision.occurred_at
            entry.summary = decision.summary
            await self._attach_backwrite_relations(
                TimelineClaim,
                "timeline_entry_id",
                entry.id,
                "claim_id",
                decision.claim_ids,
                run_id,
                [TimelineClaim.timeline_entry_id, TimelineClaim.claim_id],
            )

    async def _persist_backwrite_conflicts(
        self,
        *,
        response: ConflictAnalysisResponse,
        candidates: dict[UUID, ExistingConflictCandidate],
        run_id: UUID,
    ) -> None:
        affected_claims: dict[UUID, set[UUID]] = {}
        for decision in response.payload.new_conflicts:
            conflict = Conflict(
                id=uuid4(),
                event_id=decision.event_id,
                summary=decision.summary,
            )
            self.database.add(conflict)
            await self.database.flush()
            await self._attach_backwrite_relations(
                ConflictClaim,
                "conflict_id",
                conflict.id,
                "claim_id",
                decision.claim_ids,
                run_id,
                [ConflictClaim.conflict_id, ConflictClaim.claim_id],
            )
            await self._attach_backwrite_relations(
                ConflictSignal,
                "conflict_id",
                conflict.id,
                "signal_id",
                decision.evidence_signal_ids,
                run_id,
                [ConflictSignal.conflict_id, ConflictSignal.signal_id],
            )
            affected_claims.setdefault(decision.event_id, set()).update(decision.claim_ids)
        for decision in response.payload.existing_conflict_updates:
            candidate = candidates.get(decision.existing_conflict_id)
            if candidate is None:
                raise IntelligenceError("CONFLICT_OUTSIDE_CANDIDATES")
            conflict = await self.database.get(Conflict, decision.existing_conflict_id)
            if conflict is None or conflict.event_id != decision.event_id:
                raise IntelligenceError("CONFLICT_EVENT_MISMATCH")
            conflict.summary = decision.summary
            await self._attach_backwrite_relations(
                ConflictClaim,
                "conflict_id",
                conflict.id,
                "claim_id",
                decision.claim_ids,
                run_id,
                [ConflictClaim.conflict_id, ConflictClaim.claim_id],
            )
            await self._attach_backwrite_relations(
                ConflictSignal,
                "conflict_id",
                conflict.id,
                "signal_id",
                decision.evidence_signal_ids,
                run_id,
                [ConflictSignal.conflict_id, ConflictSignal.signal_id],
            )
            affected_claims.setdefault(decision.event_id, set()).update(
                [*candidate.claim_ids, *decision.claim_ids]
            )
        await IntelligenceRepository(self.database)._apply_conflict_states(affected_claims)

    async def _persist_backwrite_base_analysis(
        self,
        *,
        response: BaseAnalysisResponse,
        candidates: dict[UUID, ExistingBaseAnalysisCandidate],
        run_id: UUID,
    ) -> None:
        for decision in response.payload.new_analyses:
            self.database.add(
                BaseAnalysis(
                    id=uuid4(),
                    event_id=decision.event_id,
                    source_artifact_id=None,
                    source_backwrite_reconciliation_run_id=run_id,
                    summary=decision.summary,
                    event_type=decision.event_type,
                    importance=decision.importance,
                    topics=decision.topics,
                    entities=[item.model_dump(mode="json") for item in decision.entities],
                )
            )
        for decision in response.payload.existing_analysis_updates:
            candidate = candidates.get(decision.existing_base_analysis_id)
            if candidate is None:
                raise IntelligenceError("BASE_ANALYSIS_OUTSIDE_CANDIDATES")
            analysis = await self.database.get(BaseAnalysis, decision.existing_base_analysis_id)
            if analysis is None or analysis.event_id != decision.event_id:
                raise IntelligenceError("BASE_ANALYSIS_EVENT_MISMATCH")
            analysis.source_artifact_id = None
            analysis.source_backwrite_reconciliation_run_id = run_id
            analysis.summary = decision.summary
            analysis.event_type = decision.event_type
            analysis.importance = decision.importance
            analysis.topics = decision.topics
            analysis.entities = [item.model_dump(mode="json") for item in decision.entities]

    async def _attach_backwrite_relations(
        self,
        model,
        owner_column: str,
        owner_id: UUID,
        target_column: str,
        target_ids: list[UUID],
        run_id: UUID,
        conflict_columns: list,
    ) -> None:
        if not target_ids:
            return
        await self.database.execute(
            insert(model)
            .values(
                [
                    {
                        "id": uuid4(),
                        owner_column: owner_id,
                        target_column: target_id,
                        "attached_by_pipeline_run_id": None,
                        "attached_by_backwrite_reconciliation_run_id": run_id,
                    }
                    for target_id in target_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=conflict_columns)
        )

    @staticmethod
    def validate_output(
        output: BackwriteReconciliationPayload,
        value: BackwriteReconciliationInput,
    ) -> None:
        if output.item_id != value.item_id or output.event_id != value.event_id:
            raise BackwriteError("BACKWRITE_OUTPUT_INVALID")
        available = {item.canonical_signal_id for item in value.canonical_signals}
        assigned = set(output.event_update.signal_ids) if output.event_update is not None else set()
        unassigned = set(output.unassigned_signal_ids)
        if assigned | unassigned != available or assigned & unassigned:
            raise BackwriteError("BACKWRITE_OUTPUT_INVALID")
        if output.decision == "update" and not assigned:
            raise BackwriteError("BACKWRITE_OUTPUT_INVALID")

    async def _event_input(self, event_id: UUID) -> AskEventInput:
        try:
            snapshot = await ResearchRepository(self.database).fact_snapshot({event_id})
        except ResearchError as error:
            code = (
                "BACKWRITE_PRIVATE_PROVENANCE_INVALID"
                if "PRIVATE_PROVENANCE" in error.error_code
                else "BACKWRITE_FACT_SNAPSHOT_INVALID"
            )
            raise BackwriteError(code) from error
        if len(snapshot.events) != 1 or snapshot.events[0].event_id != event_id:
            raise BackwriteError("BACKWRITE_FACT_SNAPSHOT_INVALID")
        analysis = (
            await self.database.execute(
                select(BaseAnalysis).where(BaseAnalysis.event_id == event_id)
            )
        ).scalar_one_or_none()
        if analysis is None:
            raise BackwriteError("BACKWRITE_BASE_ANALYSIS_MISSING")
        return AskEventInput(
            **snapshot.events[0].model_dump(),
            base_analysis=AskBaseAnalysisInput(
                base_analysis_id=analysis.id,
                summary=analysis.summary,
                event_type=analysis.event_type,
                importance=analysis.importance,
                topics=analysis.topics,
                entities=analysis.entities,
            ),
        )

    async def _canonical_signals(
        self, source: BackwriteResearchArtifactPayload
    ) -> list[AskReconciliationSignal]:
        observation_ids = [
            signal_id for result in source.results for signal_id in result.observation_signal_ids
        ]
        if not observation_ids:
            return []
        observations = list(
            (
                await self.database.execute(select(Signal).where(Signal.id.in_(observation_ids)))
            ).scalars()
        )
        observation_map = {item.id: item for item in observations}
        if set(observation_map) != set(observation_ids):
            raise BackwriteError("BACKWRITE_RESEARCH_SIGNAL_INVALID")
        canonical_ids = {item.duplicate_of_signal_id or item.id for item in observations}
        canonical_rows = list(
            (
                await self.database.execute(
                    select(Signal).where(Signal.id.in_(canonical_ids)).order_by(Signal.id)
                )
            ).scalars()
        )
        canonical_map = {item.id: item for item in canonical_rows}
        if set(canonical_map) != canonical_ids:
            raise BackwriteError("BACKWRITE_RESEARCH_SIGNAL_INVALID")
        grouped: dict[UUID, list[UUID]] = {}
        order: list[UUID] = []
        for observation_id in observation_ids:
            observation = observation_map[observation_id]
            canonical_id = observation.duplicate_of_signal_id or observation.id
            canonical = canonical_map[canonical_id]
            if canonical.duplicate_of_signal_id is not None or (
                canonical.content_hash != observation.content_hash
            ):
                raise BackwriteError("BACKWRITE_RESEARCH_SIGNAL_INVALID")
            if canonical_id not in grouped:
                grouped[canonical_id] = []
                order.append(canonical_id)
            grouped[canonical_id].append(observation.id)
        values: list[AskReconciliationSignal] = []
        for canonical_id in order:
            signal = canonical_map[canonical_id]
            evidence = ResearchRepository._evidence(signal)
            values.append(
                AskReconciliationSignal(
                    canonical_signal_id=canonical_id,
                    observation_signal_ids=grouped[canonical_id],
                    title=signal.title,
                    sanitized_text=evidence.sanitized_text,
                    published_at=evidence.published_at,
                    evidence_visibility=evidence.evidence_visibility,
                    public_safe_provenance=evidence.public_safe_provenance,
                )
            )
        return values

    async def deduplicate_research_results(self, results: list[BackwriteResearchResult]) -> None:
        observation_ids = [
            signal_id for result in results for signal_id in result.observation_signal_ids
        ]
        if not observation_ids:
            return
        observations = list(
            (
                await self.database.execute(
                    select(Signal).where(Signal.id.in_(observation_ids)).with_for_update()
                )
            ).scalars()
        )
        observation_map = {item.id: item for item in observations}
        if set(observation_map) != set(observation_ids):
            raise BackwriteError("BACKWRITE_RESEARCH_SIGNAL_INVALID")
        content_hashes = {item.content_hash for item in observations}
        candidates = list(
            (
                await self.database.execute(
                    select(Signal)
                    .where(Signal.content_hash.in_(content_hashes))
                    .order_by(Signal.created_at, Signal.id)
                    .with_for_update()
                )
            ).scalars()
        )
        canonical_by_hash: dict[str, Signal] = {}
        for candidate in candidates:
            if candidate.duplicate_of_signal_id is None:
                canonical_by_hash.setdefault(candidate.content_hash, candidate)
        if set(canonical_by_hash) != content_hashes:
            raise BackwriteError("BACKWRITE_RESEARCH_SIGNAL_INVALID")
        for observation in observations:
            canonical = canonical_by_hash[observation.content_hash]
            observation.duplicate_of_signal_id = (
                None if observation.id == canonical.id else canonical.id
            )
        await self.database.commit()

    async def _lock_input(self, value: BackwriteReconciliationInput) -> None:
        event_id = value.event_id
        await self._lock(
            BackwriteResearchArtifact,
            BackwriteResearchArtifact.item_id == value.item_id,
            BackwriteResearchArtifact.id,
        )
        await self._lock(Event, Event.id == event_id, Event.id)
        event_signal_ids = list(
            (
                await self.database.execute(
                    select(EventSignal.signal_id).where(EventSignal.event_id == event_id)
                )
            ).scalars()
        )
        input_signal_ids = {
            signal_id
            for item in value.canonical_signals
            for signal_id in [item.canonical_signal_id, *item.observation_signal_ids]
        }
        await self._lock(
            Signal,
            Signal.id.in_(sorted(input_signal_ids | set(event_signal_ids))),
            Signal.id,
        )
        await self._lock(EventSignal, EventSignal.event_id == event_id, EventSignal.id)
        claims = await self._lock(Claim, Claim.event_id == event_id, Claim.id)
        claim_ids = [item.id for item in claims]
        await self._lock(ClaimSignal, ClaimSignal.claim_id.in_(claim_ids), ClaimSignal.id)
        timelines = await self._lock(
            TimelineEntry, TimelineEntry.event_id == event_id, TimelineEntry.id
        )
        await self._lock(
            TimelineClaim,
            TimelineClaim.timeline_entry_id.in_([item.id for item in timelines]),
            TimelineClaim.timeline_entry_id,
        )
        conflicts = await self._lock(Conflict, Conflict.event_id == event_id, Conflict.id)
        conflict_ids = [item.id for item in conflicts]
        await self._lock(
            ConflictClaim, ConflictClaim.conflict_id.in_(conflict_ids), ConflictClaim.id
        )
        await self._lock(
            ConflictSignal, ConflictSignal.conflict_id.in_(conflict_ids), ConflictSignal.id
        )
        await self._lock(BaseAnalysis, BaseAnalysis.event_id == event_id, BaseAnalysis.id)

    async def _lock(self, model, predicate, order_by):
        return list(
            (
                await self.database.execute(
                    select(model).where(predicate).order_by(order_by).with_for_update()
                )
            ).scalars()
        )

    async def _finalize_cycle(self, cycle: BackwriteCycle) -> None:
        counts = dict(
            (
                await self.database.execute(
                    select(BackwriteItem.status, func.count())
                    .where(BackwriteItem.cycle_id == cycle.id)
                    .group_by(BackwriteItem.status)
                )
            ).all()
        )
        active = sum(counts.get(value, 0) for value in ("pending", "researching", "reconciling"))
        if active:
            return
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        if failed and completed:
            cycle.status = "partial"
            cycle.error_code = "BACKWRITE_PARTIAL_FAILURE"
        elif failed:
            cycle.status = "failed"
            cycle.error_code = "BACKWRITE_ALL_ITEMS_FAILED"
        else:
            cycle.status = "completed"
            cycle.error_code = None
        cycle.finished_at = datetime.now(UTC)


class BackwriteRunner:
    def __init__(
        self,
        *,
        repository: BackwriteRepository,
        research_repository: ResearchRepository,
        research_runner: ResearchRunner,
        acquisition: AcquisitionRepository,
        client: BackwriteClient,
        max_attempts: int,
        normalizer: DeterministicNormalizer | None = None,
    ) -> None:
        self.repository = repository
        self.research_repository = research_repository
        self.research_runner = research_runner
        self.acquisition = acquisition
        self.client = client
        self.max_attempts = max_attempts
        self.normalizer = normalizer or DeterministicNormalizer()

    async def run_cycle(self, cycle_id: UUID) -> BackwriteCycle:
        while True:
            prepared = await self.repository.prepare_next_item(cycle_id)
            if prepared is None:
                cycle = await self.repository.database.get(BackwriteCycle, cycle_id)
                if cycle is None:
                    raise BackwriteError("BACKWRITE_CYCLE_NOT_FOUND")
                return cycle
            await self._run_item(prepared)

    async def _run_item(self, prepared: PreparedBackwriteItem) -> None:
        try:
            request = await self.research_runner.create_and_run(
                ResearchRequestSpec(
                    idempotency_key=uuid5(
                        BACKWRITE_RESEARCH_NAMESPACE,
                        f"{prepared.item_id}:backwrite_research.v1",
                    ),
                    trigger=ResearchTrigger.BACKWRITE_ENRICHMENT,
                    source_event_ids=[prepared.event_id],
                    research_questions=[BACKWRITE_RESEARCH_QUESTION],
                    missing_fact_descriptions=[],
                    allowed_source_kinds=[
                        ResearchSourceKind.WEB_PAGE,
                        ResearchSourceKind.GITHUB_DOCUMENT,
                    ],
                )
            )
            await self.repository.attach_research_request(prepared.item_id, request.id)
            if request.status not in {
                ResearchStatus.SUCCEEDED.value,
                ResearchStatus.PARTIAL.value,
            }:
                raise BackwriteError("BACKWRITE_RESEARCH_FAILED", retryable=True)
            sources = await self.repository.successful_sources(request.id)
            if not sources:
                raise BackwriteError("BACKWRITE_RESEARCH_NO_VALID_CANDIDATES")
            results, normalization_failures = await self._normalize_sources(sources)
            if normalization_failures == len(sources):
                raise BackwriteError("BACKWRITE_RESEARCH_NORMALIZATION_FAILED", retryable=True)
            await self.repository.deduplicate_research_results(results)
            await self.repository.persist_research_artifact(
                prepared,
                request=request,
                results=results,
            )
            value = await self.repository.input_snapshot(prepared.item_id)
            await self.repository.store_input_hash(prepared.item_id, value)
            if not value.canonical_signals:
                await self.repository.persist_no_change(prepared, value)
                return
            response = await self.client.reconcile_backwrite_event(value)
            self.repository.validate_output(response.payload, value)
            await self.repository.persist_success(
                prepared,
                original_input=value,
                response=response,
                client=self.client,
            )
        except (
            AnalysisError,
            BackwriteError,
            IntelligenceError,
            ResearchError,
            SQLAlchemyError,
        ) as error:
            await self.repository.persist_failure(
                prepared,
                error_code=getattr(error, "error_code", "BACKWRITE_FAILED"),
                retryable=getattr(error, "retryable", isinstance(error, AnalysisError)),
            )
        except Exception as error:
            # Keep an unexpected item failure auditable and prevent a worker crash from
            # leaving the item/cycle permanently active. The item remains retryable until
            # its frozen max_attempts is reached.
            logger.exception(
                "unexpected backwrite item failure item_id=%s error_type=%s",
                prepared.item_id,
                type(error).__name__,
            )
            try:
                await self.repository.persist_failure(
                    prepared,
                    error_code="BACKWRITE_FAILED",
                    retryable=True,
                )
            except Exception:
                logger.exception(
                    "backwrite failure audit persistence failed item_id=%s",
                    prepared.item_id,
                )
                raise

    async def _normalize_sources(
        self, sources: list[ResearchSource]
    ) -> tuple[list[BackwriteResearchResult], int]:
        results: list[BackwriteResearchResult] = []
        failures = 0
        for source in sources:
            if source.raw_information_id is None:
                failures += 1
                continue
            raw = await self.repository.database.get(RawInformation, source.raw_information_id)
            if raw is None or raw.source_type != "research":
                raise BackwriteError("BACKWRITE_RESEARCH_RAW_INVALID")
            if raw.normalization_status == NormalizationStatus.PROCESSING.value:
                raise BackwriteError("BACKWRITE_RESEARCH_NORMALIZATION_BUSY", retryable=True)
            if raw.normalization_status in {
                NormalizationStatus.PENDING.value,
                NormalizationStatus.FAILED.value,
            }:
                await self.acquisition.mark_normalization_started(raw)
                try:
                    normalized = self.normalizer.normalize(raw)
                except NormalizationError as error:
                    await self.acquisition.mark_normalization_failed(
                        raw,
                        error_code=error.error_code,
                    )
                    failures += 1
                    continue
                await self.acquisition.persist_signal(
                    raw=raw,
                    value=normalized,
                    normalized_at=datetime.now(UTC),
                )
            signals = list(
                (
                    await self.repository.database.execute(
                        select(Signal)
                        .where(Signal.raw_information_id == raw.id)
                        .order_by(Signal.created_at, Signal.id)
                    )
                ).scalars()
            )
            results.append(
                BackwriteResearchResult(
                    candidate_index=source.candidate_index,
                    research_source_id=source.id,
                    raw_information_id=raw.id,
                    observation_signal_ids=[item.id for item in signals],
                )
            )
        return results, failures
