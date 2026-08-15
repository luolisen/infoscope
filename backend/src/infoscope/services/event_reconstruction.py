from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.reconstruction_schemas import (
    RECONSTRUCTION_SCHEMA_VERSION,
    EventAssignment,
    EventReconstructionArtifact,
    EventReconstructionPayload,
    EventReconstructionResponse,
    ExistingEventCandidate,
)
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisPayload
from infoscope.models import (
    Event,
    EventSignal,
    EvidenceVisibility,
    PipelineArtifact,
    PipelineRun,
    PipelineRunStatus,
    Signal,
)
from infoscope.pipeline import AcquisitionCursor, LogicalWindow
from infoscope.schemas.now import EventState
from infoscope.services.pipeline import PipelineRepository

PIPELINE_NAME = "event_reconstruction"
SOURCE_ARTIFACT_TYPE = "window_analysis"
ARTIFACT_TYPE = "event_reconstruction"
logger = logging.getLogger("infoscope.pipeline.event_reconstruction")


class EventReconstructionClientProtocol(Protocol):
    async def reconstruct(
        self,
        *,
        window_analysis: WindowAnalysisPayload,
        signals: list[AnalysisSignal],
        candidates: list[ExistingEventCandidate],
    ) -> EventReconstructionResponse: ...


class EventReconstructionError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class EventReconstructionResult:
    run_id: UUID
    events_created: int
    events_updated: int
    signals_attached: int
    reused_artifact: bool


class EventRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def rollback(self) -> None:
        await self.database.rollback()

    async def source_artifact(
        self, artifact_id: UUID
    ) -> tuple[PipelineArtifact, PipelineRun] | None:
        artifact = await self.database.get(PipelineArtifact, artifact_id)
        if artifact is None:
            return None
        run = await self.database.get(PipelineRun, artifact.pipeline_run_id)
        if run is None:
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_RUN_MISSING")
        return artifact, run

    async def lock_source_artifact(self, source_artifact_id: UUID) -> None:
        locked_id = (
            await self.database.execute(
                select(PipelineArtifact.id)
                .where(PipelineArtifact.id == source_artifact_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked_id is None:
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_ARTIFACT_NOT_FOUND")

    async def signals(self, signal_ids: list[UUID]) -> list[Signal]:
        if not signal_ids:
            return []
        result = await self.database.execute(select(Signal).where(Signal.id.in_(signal_ids)))
        by_id = {signal.id: signal for signal in result.scalars()}
        if set(by_id) != set(signal_ids):
            raise EventReconstructionError("RECONSTRUCTION_SIGNAL_MISSING")
        return [by_id[signal_id] for signal_id in signal_ids]

    async def candidates(self, *, limit: int) -> list[ExistingEventCandidate]:
        result = await self.database.execute(
            select(Event).order_by(Event.updated_at.desc(), Event.id).limit(limit)
        )
        events = list(result.scalars())
        if not events:
            return []
        links = await self.database.execute(
            select(EventSignal.event_id, EventSignal.signal_id).where(
                EventSignal.event_id.in_([event.id for event in events])
            )
        )
        signal_ids: dict[UUID, list[UUID]] = {event.id: [] for event in events}
        for event_id, signal_id in links:
            signal_ids[event_id].append(signal_id)
        return [
            ExistingEventCandidate(
                event_id=event.id,
                title=event.title,
                overview=event.overview,
                state=event.state,
                display_time=event.display_time,
                signal_ids=signal_ids[event.id],
            )
            for event in events
        ]

    async def prior_source_artifact(self, source_artifact_id: UUID) -> PipelineArtifact | None:
        result = await self.database.execute(
            select(PipelineArtifact)
            .where(
                PipelineArtifact.artifact_type == ARTIFACT_TYPE,
                PipelineArtifact.source_artifact_id == source_artifact_id,
            )
            .order_by(PipelineArtifact.created_at.desc(), PipelineArtifact.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def persist_reconstruction(
        self,
        *,
        run: PipelineRun,
        source_artifact_id: UUID,
        input_hash: str,
        response: EventReconstructionResponse,
        candidate_ids: set[UUID],
    ) -> tuple[PipelineArtifact, int, int, int, bool]:
        assignments: list[EventAssignment] = []
        created = 0
        updated = 0
        attached = 0

        for decision in response.payload.new_events:
            event_id = uuid4()
            self.database.add(
                Event(
                    id=event_id,
                    title=decision.title,
                    overview=decision.overview,
                    state=self._next_event_state(current_state=None),
                    display_time=decision.display_time,
                )
            )
            assignments.append(
                EventAssignment(
                    decision_key=decision.decision_key,
                    event_id=event_id,
                    decision_type="new",
                )
            )
            attached += await self._attach_signals(
                event_id=event_id,
                signal_ids=decision.signal_ids,
                run_id=run.id,
            )
            created += 1

        for decision in response.payload.existing_event_updates:
            if decision.existing_event_id not in candidate_ids:
                raise EventReconstructionError("RECONSTRUCTION_EVENT_OUTSIDE_CANDIDATES")
            event = await self.database.get(Event, decision.existing_event_id)
            if event is None:
                raise EventReconstructionError("RECONSTRUCTION_EVENT_MISSING")
            event.title = decision.title
            event.overview = decision.overview
            event.state = self._next_event_state(current_state=event.state)
            event.display_time = decision.display_time
            assignments.append(
                EventAssignment(
                    decision_key=decision.decision_key,
                    event_id=event.id,
                    decision_type="update",
                )
            )
            attached += await self._attach_signals(
                event_id=event.id,
                signal_ids=decision.signal_ids,
                run_id=run.id,
            )
            updated += 1

        artifact_payload = EventReconstructionArtifact(
            source_artifact_id=source_artifact_id,
            model_output=response.payload,
            assignments=assignments,
        )
        artifact = PipelineArtifact(
            id=uuid4(),
            pipeline_run_id=run.id,
            source_artifact_id=source_artifact_id,
            artifact_type=ARTIFACT_TYPE,
            schema_version=RECONSTRUCTION_SCHEMA_VERSION,
            input_hash=input_hash,
            payload=artifact_payload.model_dump(mode="json"),
            provider=response.provider,
            model=response.model,
            token_usage=response.token_usage.model_dump(mode="json"),
        )
        self.database.add(artifact)
        run_id = run.id
        try:
            await self.database.commit()
        except IntegrityError as error:
            if self._constraint_name(error) != "uq_pipeline_artifacts_type_source":
                raise
            await self.database.rollback()
            persisted_run = await self.database.get(PipelineRun, run_id)
            if persisted_run is None:
                raise EventReconstructionError("RECONSTRUCTION_RUN_MISSING") from error
            await self.database.refresh(persisted_run)
            prior = await self.prior_source_artifact(source_artifact_id)
            if prior is None:
                raise EventReconstructionError(
                    "RECONSTRUCTION_IDEMPOTENCY_CONFLICT_MISSING"
                ) from error
            return prior, 0, 0, 0, True
        return artifact, created, updated, attached, False

    @staticmethod
    def _next_event_state(*, current_state: str | None) -> str:
        if current_state is None:
            return EventState.DEVELOPING.value
        try:
            return EventState(current_state).value
        except ValueError as error:
            raise EventReconstructionError("RECONSTRUCTION_EVENT_STATE_INVALID") from error

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        original = getattr(error, "orig", None)
        for candidate in (original, getattr(original, "__cause__", None)):
            diagnostic = getattr(candidate, "diag", None)
            constraint_name = getattr(diagnostic, "constraint_name", None) or getattr(
                candidate, "constraint_name", None
            )
            if constraint_name is not None:
                return constraint_name
        return None

    async def _attach_signals(
        self,
        *,
        event_id: UUID,
        signal_ids: list[UUID],
        run_id: UUID,
    ) -> int:
        if not signal_ids:
            return 0
        statement = (
            insert(EventSignal)
            .values(
                [
                    {
                        "id": uuid4(),
                        "event_id": event_id,
                        "signal_id": signal_id,
                        "attached_by_pipeline_run_id": run_id,
                    }
                    for signal_id in signal_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[EventSignal.event_id, EventSignal.signal_id]
            )
            .returning(EventSignal.id)
        )
        return len(list((await self.database.execute(statement)).scalars()))


class EventReconstructionRunner:
    def __init__(
        self,
        *,
        events: EventRepository,
        pipeline: PipelineRepository,
        client: EventReconstructionClientProtocol,
        candidate_limit: int = 100,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        if candidate_limit <= 0:
            raise ValueError("candidate_limit must be positive")
        self.events = events
        self.pipeline = pipeline
        self.client = client
        self.candidate_limit = candidate_limit
        self.clock = clock

    async def reconstruct(self, source_artifact_id: UUID) -> EventReconstructionResult:
        source = await self.events.source_artifact(source_artifact_id)
        if source is None:
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_ARTIFACT_NOT_FOUND")
        source_artifact, source_run = source
        self._validate_source(source_artifact, source_run)
        window = LogicalWindow(start=source_run.window_start, end=source_run.window_end)
        run = await self.pipeline.start_run(
            pipeline_name=PIPELINE_NAME,
            window=window,
            started_at=self.clock(),
            lower_cursor=self._cursor(
                source_run.lower_cursor_acquired_at,
                source_run.lower_cursor_raw_id,
            ),
        )
        logger.info(
            "pipeline run started pipeline=%s run_id=%s source_artifact_id=%s "
            "window_start=%s window_end=%s attempt=%s",
            PIPELINE_NAME,
            run.id,
            source_artifact_id,
            window.start.isoformat(),
            window.end.isoformat(),
            run.attempt,
        )
        try:
            result = await self._execute(
                run=run,
                source_artifact=source_artifact,
                source_run=source_run,
            )
        except (AnalysisError, EventReconstructionError, SQLAlchemyError) as error:
            run_id = run.id
            await self.events.rollback()
            persisted_run = await self.pipeline.get_run(run_id)
            if persisted_run is None:
                raise EventReconstructionError("RECONSTRUCTION_RUN_MISSING") from error
            run = persisted_run
            error_code = (
                error.error_code
                if isinstance(error, (AnalysisError, EventReconstructionError))
                else "RECONSTRUCTION_PERSISTENCE_FAILED"
            )
            retry_at = self.clock() + timedelta(minutes=5)
            await self.pipeline.fail_run(
                run,
                finished_at=self.clock(),
                next_retry_at=retry_at,
                error_code=error_code,
            )
            logger.warning(
                "pipeline run failed pipeline=%s run_id=%s source_artifact_id=%s "
                "attempt=%s error_code=%s next_retry_at=%s",
                PIPELINE_NAME,
                run.id,
                source_artifact_id,
                run.attempt,
                error_code,
                retry_at.isoformat(),
            )
            if isinstance(error, SQLAlchemyError):
                raise EventReconstructionError(error_code) from error
            raise
        logger.info(
            "pipeline run succeeded pipeline=%s run_id=%s source_artifact_id=%s "
            "created=%d updated=%d attached=%d reused=%s",
            PIPELINE_NAME,
            run.id,
            source_artifact_id,
            result.events_created,
            result.events_updated,
            result.signals_attached,
            result.reused_artifact,
        )
        return result

    async def _execute(
        self,
        *,
        run: PipelineRun,
        source_artifact: PipelineArtifact,
        source_run: PipelineRun,
    ) -> EventReconstructionResult:
        try:
            window_analysis = WindowAnalysisPayload.model_validate(source_artifact.payload)
        except ValueError as error:
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_SCHEMA_INVALID") from error
        await self.events.lock_source_artifact(source_artifact.id)
        prior = await self.events.prior_source_artifact(source_artifact.id)
        upper_cursor = self._cursor(
            source_run.upper_cursor_acquired_at,
            source_run.upper_cursor_raw_id,
        )
        if prior is not None:
            try:
                EventReconstructionArtifact.model_validate(prior.payload)
            except ValueError as error:
                raise EventReconstructionError(
                    "RECONSTRUCTION_PRIOR_ARTIFACT_INVALID"
                ) from error
            await self.pipeline.complete_run(
                run,
                finished_at=self.clock(),
                upper_cursor=upper_cursor,
            )
            return EventReconstructionResult(run.id, 0, 0, 0, True)

        signal_ids = [item.signal_id for item in window_analysis.signal_analyses]
        stored_signals = await self.events.signals(signal_ids)
        signals = [self._analysis_signal(signal) for signal in stored_signals]
        candidates = await self.events.candidates(limit=self.candidate_limit)
        input_hash = self._input_hash(
            source_artifact=source_artifact,
            signals=signals,
            candidates=candidates,
        )
        response = await self.client.reconstruct(
            window_analysis=window_analysis,
            signals=signals,
            candidates=candidates,
        )
        self._validate_output(
            payload=response.payload,
            expected_signal_ids=set(signal_ids),
            candidate_ids={candidate.event_id for candidate in candidates},
        )
        _, created, updated, attached, reused = await self.events.persist_reconstruction(
            run=run,
            source_artifact_id=source_artifact.id,
            input_hash=input_hash,
            response=response,
            candidate_ids={candidate.event_id for candidate in candidates},
        )
        await self.pipeline.complete_run(
            run,
            finished_at=self.clock(),
            upper_cursor=upper_cursor,
        )
        return EventReconstructionResult(run.id, created, updated, attached, reused)

    @staticmethod
    def _validate_source(artifact: PipelineArtifact, run: PipelineRun) -> None:
        if (
            artifact.artifact_type != SOURCE_ARTIFACT_TYPE
            or artifact.schema_version != "window_analysis.v1"
        ):
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_ARTIFACT_INVALID")
        if (
            run.pipeline_name != "window_analysis"
            or run.status != PipelineRunStatus.SUCCEEDED.value
        ):
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_RUN_NOT_SUCCEEDED")

    @staticmethod
    def _analysis_signal(signal: Signal) -> AnalysisSignal:
        if (
            signal.evidence_visibility == EvidenceVisibility.PRIVATE_SANITIZED.value
            and signal.public_provenance is not None
        ):
            raise EventReconstructionError("RECONSTRUCTION_PRIVATE_PROVENANCE_INVALID")
        return AnalysisSignal(
            signal_id=signal.id,
            title=signal.title,
            text=signal.normalized_text,
            published_at=signal.published_at,
            source_type=signal.source_type,
            evidence_visibility=signal.evidence_visibility,
            public_provenance=signal.public_provenance,
        )

    @staticmethod
    def _validate_output(
        *,
        payload: EventReconstructionPayload,
        expected_signal_ids: set[UUID],
        candidate_ids: set[UUID],
    ) -> None:
        decisions = [*payload.new_events, *payload.existing_event_updates]
        covered = {signal_id for decision in decisions for signal_id in decision.signal_ids}
        covered |= set(payload.unassigned_signal_ids)
        if covered != expected_signal_ids:
            raise EventReconstructionError("RECONSTRUCTION_SIGNAL_COVERAGE_INVALID")
        referenced = {
            decision.existing_event_id for decision in payload.existing_event_updates
        }
        if not referenced <= candidate_ids:
            raise EventReconstructionError("RECONSTRUCTION_EVENT_OUTSIDE_CANDIDATES")
        if any(
            decision.display_time.tzinfo is None
            or decision.display_time.utcoffset() is None
            for decision in decisions
        ):
            raise EventReconstructionError("RECONSTRUCTION_DISPLAY_TIME_INVALID")

    @staticmethod
    def _input_hash(
        *,
        source_artifact: PipelineArtifact,
        signals: list[AnalysisSignal],
        candidates: list[ExistingEventCandidate],
    ) -> str:
        document = {
            "source_artifact_id": str(source_artifact.id),
            "source_input_hash": source_artifact.input_hash,
            "signals": [signal.model_dump(mode="json") for signal in signals],
            "candidate_events": [candidate.model_dump(mode="json") for candidate in candidates],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _cursor(acquired_at: datetime | None, raw_id: UUID | None) -> AcquisitionCursor | None:
        if acquired_at is None:
            if raw_id is not None:
                raise EventReconstructionError("RECONSTRUCTION_SOURCE_CURSOR_INVALID")
            return None
        if raw_id is None:
            raise EventReconstructionError("RECONSTRUCTION_SOURCE_CURSOR_INVALID")
        return AcquisitionCursor(acquired_at, raw_id)
