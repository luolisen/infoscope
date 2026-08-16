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
from infoscope.analysis.intelligence_schemas import (
    ClaimAssignment,
    ClaimExtractionArtifact,
    ClaimExtractionPayload,
    ClaimExtractionResponse,
    ClaimTimelineInput,
    EventClaimInput,
    ExistingClaimCandidate,
    ExistingTimelineCandidate,
    TimelineAssignment,
    TimelineReconstructionArtifact,
    TimelineReconstructionPayload,
    TimelineReconstructionResponse,
)
from infoscope.analysis.reconstruction_schemas import EventReconstructionArtifact
from infoscope.analysis.schemas import AnalysisSignal
from infoscope.models import (
    Claim,
    ClaimSignal,
    Event,
    EventSignal,
    EvidenceVisibility,
    PipelineArtifact,
    PipelineRun,
    PipelineRunStatus,
    Signal,
    TimelineClaim,
    TimelineEntry,
)
from infoscope.pipeline import AcquisitionCursor, LogicalWindow
from infoscope.services.pipeline import PipelineRepository

logger = logging.getLogger("infoscope.pipeline.claims_timeline")
CLAIM_PIPELINE = "claim_extraction"
CLAIM_ARTIFACT = "claim_extraction"
TIMELINE_PIPELINE = "timeline_reconstruction"
TIMELINE_ARTIFACT = "timeline_reconstruction"
CLAIM_STATES = {"confirmed", "unresolved", "conflicting", "contradicted"}


class IntelligenceClientProtocol(Protocol):
    async def extract_claims(
        self, *, events: list[EventClaimInput], candidates: list[ExistingClaimCandidate]
    ) -> ClaimExtractionResponse: ...

    async def reconstruct_timeline(
        self, *, claims: list[ClaimTimelineInput], candidates: list[ExistingTimelineCandidate]
    ) -> TimelineReconstructionResponse: ...


class IntelligenceError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class IntelligenceResult:
    run_id: UUID
    created: int
    updated: int
    attached: int
    reused_artifact: bool


class IntelligenceRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def rollback(self) -> None:
        await self.database.rollback()

    async def artifact_with_run(
        self, artifact_id: UUID
    ) -> tuple[PipelineArtifact, PipelineRun] | None:
        artifact = await self.database.get(PipelineArtifact, artifact_id)
        if artifact is None:
            return None
        run = await self.database.get(PipelineRun, artifact.pipeline_run_id)
        if run is None:
            raise IntelligenceError("INTELLIGENCE_SOURCE_RUN_MISSING")
        return artifact, run

    async def lock_source(self, artifact_id: UUID) -> None:
        value = (
            await self.database.execute(
                select(PipelineArtifact.id)
                .where(PipelineArtifact.id == artifact_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if value is None:
            raise IntelligenceError("INTELLIGENCE_SOURCE_ARTIFACT_NOT_FOUND")

    async def prior(self, artifact_type: str, source_artifact_id: UUID) -> PipelineArtifact | None:
        return (
            await self.database.execute(
                select(PipelineArtifact).where(
                    PipelineArtifact.artifact_type == artifact_type,
                    PipelineArtifact.source_artifact_id == source_artifact_id,
                )
            )
        ).scalar_one_or_none()

    async def claim_inputs(
        self, event_ids: set[UUID]
    ) -> tuple[list[EventClaimInput], list[ExistingClaimCandidate]]:
        events = (
            list(
                (
                    await self.database.execute(select(Event).where(Event.id.in_(event_ids)))
                ).scalars()
            )
            if event_ids
            else []
        )
        if {item.id for item in events} != event_ids:
            raise IntelligenceError("CLAIM_EVENT_MISSING")
        rows = (
            (
                await self.database.execute(
                    select(EventSignal.event_id, Signal)
                    .join(Signal, Signal.id == EventSignal.signal_id)
                    .where(EventSignal.event_id.in_(event_ids))
                )
            ).all()
            if event_ids
            else []
        )
        signals: dict[UUID, list[AnalysisSignal]] = {event_id: [] for event_id in event_ids}
        for event_id, signal in rows:
            signals[event_id].append(self._analysis_signal(signal))
        claim_rows = (
            list(
                (
                    await self.database.execute(select(Claim).where(Claim.event_id.in_(event_ids)))
                ).scalars()
            )
            if event_ids
            else []
        )
        link_rows = (
            (
                await self.database.execute(
                    select(ClaimSignal.claim_id, ClaimSignal.signal_id).where(
                        ClaimSignal.claim_id.in_([item.id for item in claim_rows])
                    )
                )
            ).all()
            if claim_rows
            else []
        )
        links: dict[UUID, list[UUID]] = {item.id: [] for item in claim_rows}
        for claim_id, signal_id in link_rows:
            links[claim_id].append(signal_id)
        return (
            [
                EventClaimInput(
                    event_id=item.id,
                    title=item.title,
                    overview=item.overview,
                    signals=signals[item.id],
                )
                for item in events
            ],
            [
                ExistingClaimCandidate(
                    claim_id=item.id,
                    event_id=item.event_id,
                    text=item.text,
                    state=item.state,
                    evidence_signal_ids=links[item.id],
                )
                for item in claim_rows
            ],
        )

    async def timeline_inputs(
        self, event_ids: set[UUID]
    ) -> tuple[list[ClaimTimelineInput], list[ExistingTimelineCandidate]]:
        claims = (
            list(
                (
                    await self.database.execute(select(Claim).where(Claim.event_id.in_(event_ids)))
                ).scalars()
            )
            if event_ids
            else []
        )
        claim_links = (
            (
                await self.database.execute(
                    select(ClaimSignal.claim_id, ClaimSignal.signal_id).where(
                        ClaimSignal.claim_id.in_([item.id for item in claims])
                    )
                )
            ).all()
            if claims
            else []
        )
        evidence: dict[UUID, list[UUID]] = {item.id: [] for item in claims}
        for claim_id, signal_id in claim_links:
            evidence[claim_id].append(signal_id)
        entries = (
            list(
                (
                    await self.database.execute(
                        select(TimelineEntry).where(TimelineEntry.event_id.in_(event_ids))
                    )
                ).scalars()
            )
            if event_ids
            else []
        )
        timeline_links = (
            (
                await self.database.execute(
                    select(TimelineClaim.timeline_entry_id, TimelineClaim.claim_id).where(
                        TimelineClaim.timeline_entry_id.in_([item.id for item in entries])
                    )
                )
            ).all()
            if entries
            else []
        )
        linked_claims: dict[UUID, list[UUID]] = {item.id: [] for item in entries}
        for entry_id, claim_id in timeline_links:
            linked_claims[entry_id].append(claim_id)
        return (
            [
                ClaimTimelineInput(
                    claim_id=item.id,
                    event_id=item.event_id,
                    text=item.text,
                    state=item.state,
                    evidence_signal_ids=evidence[item.id],
                )
                for item in claims
            ],
            [
                ExistingTimelineCandidate(
                    timeline_entry_id=item.id,
                    event_id=item.event_id,
                    occurred_at=item.occurred_at,
                    summary=item.summary,
                    claim_ids=linked_claims[item.id],
                )
                for item in entries
            ],
        )

    async def persist_claims(
        self,
        *,
        run: PipelineRun,
        source_artifact_id: UUID,
        input_hash: str,
        response: ClaimExtractionResponse,
        candidate_ids: set[UUID],
    ) -> tuple[int, int, int, bool]:
        assignments: list[ClaimAssignment] = []
        created = updated = attached = 0
        for decision in response.payload.new_claims:
            claim_id = uuid4()
            self.database.add(
                Claim(
                    id=claim_id, event_id=decision.event_id, text=decision.text, state="unresolved"
                )
            )
            assignments.append(
                ClaimAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    claim_id=claim_id,
                    decision_type="new",
                )
            )
            attached += await self._attach_claim_signals(
                claim_id, decision.evidence_signal_ids, run.id
            )
            created += 1
        for decision in response.payload.existing_claim_updates:
            if decision.existing_claim_id not in candidate_ids:
                raise IntelligenceError("CLAIM_OUTSIDE_CANDIDATES")
            claim = await self.database.get(Claim, decision.existing_claim_id)
            if claim is None or claim.event_id != decision.event_id:
                raise IntelligenceError("CLAIM_EVENT_MISMATCH")
            if claim.state not in CLAIM_STATES:
                raise IntelligenceError("CLAIM_STATE_INVALID")
            claim.text = decision.text
            assignments.append(
                ClaimAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    claim_id=claim.id,
                    decision_type="update",
                )
            )
            attached += await self._attach_claim_signals(
                claim.id, decision.evidence_signal_ids, run.id
            )
            updated += 1
        payload = ClaimExtractionArtifact(
            source_artifact_id=source_artifact_id,
            model_output=response.payload,
            assignments=assignments,
        )
        self.database.add(
            PipelineArtifact(
                id=uuid4(),
                pipeline_run_id=run.id,
                source_artifact_id=source_artifact_id,
                artifact_type=CLAIM_ARTIFACT,
                schema_version="claim_extraction.v1",
                input_hash=input_hash,
                payload=payload.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
        )
        return await self._commit_or_reuse(
            run, source_artifact_id, created, updated, attached, CLAIM_ARTIFACT
        )

    async def persist_timeline(
        self,
        *,
        run: PipelineRun,
        source_artifact_id: UUID,
        input_hash: str,
        response: TimelineReconstructionResponse,
        candidate_ids: set[UUID],
    ) -> tuple[int, int, int, bool]:
        assignments: list[TimelineAssignment] = []
        created = updated = attached = 0
        for decision in response.payload.new_entries:
            entry_id = uuid4()
            self.database.add(
                TimelineEntry(
                    id=entry_id,
                    event_id=decision.event_id,
                    occurred_at=decision.occurred_at,
                    summary=decision.summary,
                )
            )
            assignments.append(
                TimelineAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    timeline_entry_id=entry_id,
                    decision_type="new",
                )
            )
            attached += await self._attach_timeline_claims(entry_id, decision.claim_ids, run.id)
            created += 1
        for decision in response.payload.existing_entry_updates:
            if decision.existing_timeline_entry_id not in candidate_ids:
                raise IntelligenceError("TIMELINE_OUTSIDE_CANDIDATES")
            entry = await self.database.get(TimelineEntry, decision.existing_timeline_entry_id)
            if entry is None or entry.event_id != decision.event_id:
                raise IntelligenceError("TIMELINE_EVENT_MISMATCH")
            entry.occurred_at = decision.occurred_at
            entry.summary = decision.summary
            assignments.append(
                TimelineAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    timeline_entry_id=entry.id,
                    decision_type="update",
                )
            )
            attached += await self._attach_timeline_claims(entry.id, decision.claim_ids, run.id)
            updated += 1
        payload = TimelineReconstructionArtifact(
            source_artifact_id=source_artifact_id,
            model_output=response.payload,
            assignments=assignments,
        )
        self.database.add(
            PipelineArtifact(
                id=uuid4(),
                pipeline_run_id=run.id,
                source_artifact_id=source_artifact_id,
                artifact_type=TIMELINE_ARTIFACT,
                schema_version="timeline_reconstruction.v1",
                input_hash=input_hash,
                payload=payload.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
        )
        return await self._commit_or_reuse(
            run, source_artifact_id, created, updated, attached, TIMELINE_ARTIFACT
        )

    async def _commit_or_reuse(
        self,
        run: PipelineRun,
        source_artifact_id: UUID,
        created: int,
        updated: int,
        attached: int,
        artifact_type: str,
    ) -> tuple[int, int, int, bool]:
        run_id = run.id
        try:
            await self.database.commit()
            return created, updated, attached, False
        except IntegrityError as error:
            if self._constraint_name(error) != "uq_pipeline_artifacts_type_source":
                raise
            await self.database.rollback()
            persisted_run = await self.database.get(PipelineRun, run_id)
            if persisted_run is None:
                raise IntelligenceError("INTELLIGENCE_RUN_MISSING") from error
            await self.database.refresh(persisted_run)
            if await self.prior(artifact_type, source_artifact_id) is None:
                raise IntelligenceError("INTELLIGENCE_IDEMPOTENCY_CONFLICT_MISSING") from error
            return 0, 0, 0, True

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        original = getattr(error, "orig", None)
        for candidate in (original, getattr(original, "__cause__", None)):
            diagnostic = getattr(candidate, "diag", None)
            value = getattr(diagnostic, "constraint_name", None) or getattr(
                candidate, "constraint_name", None
            )
            if value is not None:
                return value
        return None

    async def _attach_claim_signals(
        self, claim_id: UUID, signal_ids: list[UUID], run_id: UUID
    ) -> int:
        result = await self.database.execute(
            insert(ClaimSignal)
            .values(
                [
                    {
                        "id": uuid4(),
                        "claim_id": claim_id,
                        "signal_id": value,
                        "attached_by_pipeline_run_id": run_id,
                    }
                    for value in signal_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=[ClaimSignal.claim_id, ClaimSignal.signal_id])
            .returning(ClaimSignal.id)
        )
        return len(list(result.scalars()))

    async def _attach_timeline_claims(
        self, entry_id: UUID, claim_ids: list[UUID], run_id: UUID
    ) -> int:
        result = await self.database.execute(
            insert(TimelineClaim)
            .values(
                [
                    {
                        "id": uuid4(),
                        "timeline_entry_id": entry_id,
                        "claim_id": value,
                        "attached_by_pipeline_run_id": run_id,
                    }
                    for value in claim_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[TimelineClaim.timeline_entry_id, TimelineClaim.claim_id]
            )
            .returning(TimelineClaim.id)
        )
        return len(list(result.scalars()))

    @staticmethod
    def _analysis_signal(signal: Signal) -> AnalysisSignal:
        if (
            signal.evidence_visibility == EvidenceVisibility.PRIVATE_SANITIZED.value
            and signal.public_provenance is not None
        ):
            raise IntelligenceError("INTELLIGENCE_PRIVATE_PROVENANCE_INVALID")
        return AnalysisSignal(
            signal_id=signal.id,
            title=signal.title,
            text=signal.normalized_text,
            published_at=signal.published_at,
            source_type=signal.source_type,
            evidence_visibility=signal.evidence_visibility,
            public_provenance=signal.public_provenance,
        )


class _BaseRunner:
    pipeline_name: str
    artifact_type: str

    def __init__(
        self,
        *,
        repository: IntelligenceRepository,
        pipeline: PipelineRepository,
        client: IntelligenceClientProtocol,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.pipeline = pipeline
        self.client = client
        self.clock = clock

    async def _prepare(
        self, source_artifact_id: UUID
    ) -> tuple[PipelineArtifact, PipelineRun, PipelineRun]:
        source = await self.repository.artifact_with_run(source_artifact_id)
        if source is None:
            raise IntelligenceError("INTELLIGENCE_SOURCE_ARTIFACT_NOT_FOUND")
        artifact, source_run = source
        self._validate_source(artifact, source_run)
        run = await self.pipeline.start_run(
            pipeline_name=self.pipeline_name,
            window=LogicalWindow(start=source_run.window_start, end=source_run.window_end),
            started_at=self.clock(),
            lower_cursor=self._cursor(
                source_run.lower_cursor_acquired_at, source_run.lower_cursor_raw_id
            ),
        )
        return artifact, source_run, run

    async def _reuse(self, run: PipelineRun, source_run: PipelineRun) -> IntelligenceResult:
        await self.pipeline.complete_run(
            run,
            finished_at=self.clock(),
            upper_cursor=self._cursor(
                source_run.upper_cursor_acquired_at, source_run.upper_cursor_raw_id
            ),
        )
        return IntelligenceResult(run.id, 0, 0, 0, True)

    async def _fail(self, run: PipelineRun, error: Exception) -> None:
        run_id = run.id
        await self.repository.rollback()
        persisted = await self.pipeline.get_run(run_id)
        if persisted is None:
            raise IntelligenceError("INTELLIGENCE_RUN_MISSING") from error
        code = (
            error.error_code
            if isinstance(error, (IntelligenceError, AnalysisError))
            else "INTELLIGENCE_PERSISTENCE_FAILED"
        )
        await self.pipeline.fail_run(
            persisted,
            finished_at=self.clock(),
            next_retry_at=self.clock() + timedelta(minutes=5),
            error_code=code,
        )

    @staticmethod
    def _cursor(at: datetime | None, raw_id: UUID | None) -> AcquisitionCursor | None:
        if at is None:
            if raw_id is not None:
                raise IntelligenceError("INTELLIGENCE_SOURCE_CURSOR_INVALID")
            return None
        if raw_id is None:
            raise IntelligenceError("INTELLIGENCE_SOURCE_CURSOR_INVALID")
        return AcquisitionCursor(at, raw_id)

    def _validate_source(self, artifact: PipelineArtifact, run: PipelineRun) -> None:
        raise NotImplementedError

    @staticmethod
    def _input_hash(
        source: PipelineArtifact, inputs: list[object], candidates: list[object]
    ) -> str:
        def dump(value: object) -> object:
            model_dump = value.model_dump  # type: ignore[attr-defined]
            return model_dump(mode="json")

        document = {
            "source_artifact_id": str(source.id),
            "source_input_hash": source.input_hash,
            "inputs": [dump(item) for item in inputs],
            "candidates": [dump(item) for item in candidates],
        }
        canonical = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class ClaimExtractionRunner(_BaseRunner):
    pipeline_name = CLAIM_PIPELINE
    artifact_type = CLAIM_ARTIFACT

    def _validate_source(self, artifact: PipelineArtifact, run: PipelineRun) -> None:
        if (
            artifact.artifact_type != "event_reconstruction"
            or artifact.schema_version != "event_reconstruction.v1"
            or run.pipeline_name != "event_reconstruction"
            or run.status != PipelineRunStatus.SUCCEEDED.value
        ):
            raise IntelligenceError("CLAIM_SOURCE_INVALID")

    async def run(self, source_artifact_id: UUID) -> IntelligenceResult:
        source, source_run, run = await self._prepare(source_artifact_id)
        try:
            await self.repository.lock_source(source.id)
            if await self.repository.prior(self.artifact_type, source.id):
                return await self._reuse(run, source_run)
            try:
                parsed = EventReconstructionArtifact.model_validate(source.payload)
            except ValueError as error:
                raise IntelligenceError("CLAIM_SOURCE_SCHEMA_INVALID") from error
            event_ids = {item.event_id for item in parsed.assignments}
            events, candidates = await self.repository.claim_inputs(event_ids)
            response = await self.client.extract_claims(events=events, candidates=candidates)
            self._validate(response.payload, events, candidates)
            created, updated, attached, reused = await self.repository.persist_claims(
                run=run,
                source_artifact_id=source.id,
                input_hash=self._input_hash(source, events, candidates),
                response=response,
                candidate_ids={item.claim_id for item in candidates},
            )
            await self.pipeline.complete_run(
                run,
                finished_at=self.clock(),
                upper_cursor=self._cursor(
                    source_run.upper_cursor_acquired_at, source_run.upper_cursor_raw_id
                ),
            )
            return IntelligenceResult(run.id, created, updated, attached, reused)
        except (
            AnalysisError,
            IntelligenceError,
            SQLAlchemyError,
        ) as error:
            await self._fail(run, error)
            raise

    @staticmethod
    def _validate(
        payload: ClaimExtractionPayload,
        events: list[EventClaimInput],
        candidates: list[ExistingClaimCandidate],
    ) -> None:
        event_signals = {
            item.event_id: {signal.signal_id for signal in item.signals} for item in events
        }
        expected = set().union(*event_signals.values()) if event_signals else set()
        decisions = [*payload.new_claims, *payload.existing_claim_updates]
        for item in decisions:
            if (
                item.event_id not in event_signals
                or not set(item.evidence_signal_ids) <= event_signals[item.event_id]
            ):
                raise IntelligenceError("CLAIM_EVIDENCE_INVALID")
        if {value for item in decisions for value in item.evidence_signal_ids} | set(
            payload.unused_signal_ids
        ) != expected:
            raise IntelligenceError("CLAIM_SIGNAL_COVERAGE_INVALID")
        by_id = {item.claim_id: item.event_id for item in candidates}
        if any(
            by_id.get(item.existing_claim_id) != item.event_id
            for item in payload.existing_claim_updates
        ):
            raise IntelligenceError("CLAIM_OUTSIDE_CANDIDATES")


class TimelineReconstructionRunner(_BaseRunner):
    pipeline_name = TIMELINE_PIPELINE
    artifact_type = TIMELINE_ARTIFACT

    def _validate_source(self, artifact: PipelineArtifact, run: PipelineRun) -> None:
        if (
            artifact.artifact_type != CLAIM_ARTIFACT
            or artifact.schema_version != "claim_extraction.v1"
            or run.pipeline_name != CLAIM_PIPELINE
            or run.status != PipelineRunStatus.SUCCEEDED.value
        ):
            raise IntelligenceError("TIMELINE_SOURCE_INVALID")

    async def run(self, source_artifact_id: UUID) -> IntelligenceResult:
        source, source_run, run = await self._prepare(source_artifact_id)
        try:
            await self.repository.lock_source(source.id)
            if await self.repository.prior(self.artifact_type, source.id):
                return await self._reuse(run, source_run)
            try:
                parsed = ClaimExtractionArtifact.model_validate(source.payload)
            except ValueError as error:
                raise IntelligenceError("TIMELINE_SOURCE_SCHEMA_INVALID") from error
            event_ids = {item.event_id for item in parsed.assignments}
            claims, candidates = await self.repository.timeline_inputs(event_ids)
            response = await self.client.reconstruct_timeline(claims=claims, candidates=candidates)
            self._validate(response.payload, claims, candidates)
            created, updated, attached, reused = await self.repository.persist_timeline(
                run=run,
                source_artifact_id=source.id,
                input_hash=self._input_hash(source, claims, candidates),
                response=response,
                candidate_ids={item.timeline_entry_id for item in candidates},
            )
            await self.pipeline.complete_run(
                run,
                finished_at=self.clock(),
                upper_cursor=self._cursor(
                    source_run.upper_cursor_acquired_at, source_run.upper_cursor_raw_id
                ),
            )
            return IntelligenceResult(run.id, created, updated, attached, reused)
        except (AnalysisError, IntelligenceError, SQLAlchemyError) as error:
            await self._fail(run, error)
            raise

    @staticmethod
    def _validate(
        payload: TimelineReconstructionPayload,
        claims: list[ClaimTimelineInput],
        candidates: list[ExistingTimelineCandidate],
    ) -> None:
        claim_events = {item.claim_id: item.event_id for item in claims}
        decisions = [*payload.new_entries, *payload.existing_entry_updates]
        for item in decisions:
            if any(claim_events.get(claim_id) != item.event_id for claim_id in item.claim_ids):
                raise IntelligenceError("TIMELINE_CLAIM_INVALID")
            if item.occurred_at.tzinfo is None or item.occurred_at.utcoffset() is None:
                raise IntelligenceError("TIMELINE_OCCURRED_AT_INVALID")
        if {value for item in decisions for value in item.claim_ids} | set(
            payload.unused_claim_ids
        ) != set(claim_events):
            raise IntelligenceError("TIMELINE_CLAIM_COVERAGE_INVALID")
        by_id = {item.timeline_entry_id: item.event_id for item in candidates}
        if any(
            by_id.get(item.existing_timeline_entry_id) != item.event_id
            for item in payload.existing_entry_updates
        ):
            raise IntelligenceError("TIMELINE_OUTSIDE_CANDIDATES")
