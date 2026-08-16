from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.intelligence_schemas import (
    BaseAnalysisArtifact,
    BaseAnalysisAssignment,
    BaseAnalysisClaimInput,
    BaseAnalysisConflictInput,
    BaseAnalysisPayload,
    BaseAnalysisResponse,
    BaseAnalysisTimelineInput,
    ConflictAnalysisArtifact,
    ConflictEvidenceSignal,
    EventBaseAnalysisInput,
    ExistingBaseAnalysisCandidate,
)
from infoscope.analysis.schemas import TokenUsage
from infoscope.models import (
    BaseAnalysis,
    Claim,
    ClaimSignal,
    Conflict,
    ConflictClaim,
    ConflictSignal,
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
from infoscope.services.claims_timeline import (
    IntelligenceError,
    IntelligenceRepository,
    IntelligenceResult,
    IntelligenceRunnerBase,
)
from infoscope.services.pipeline import PipelineRepository

BASE_ANALYSIS_PIPELINE = "base_analysis"
BASE_ANALYSIS_ARTIFACT = "base_analysis"


class BaseAnalysisClientProtocol(Protocol):
    async def analyze_base(
        self,
        *,
        events: list[EventBaseAnalysisInput],
        candidates: list[ExistingBaseAnalysisCandidate],
    ) -> BaseAnalysisResponse: ...


class BaseAnalysisRepository(IntelligenceRepository):
    async def event_ids_for_unconflicted_claims(self, claim_ids: set[UUID]) -> set[UUID]:
        if not claim_ids:
            return set()
        rows = (
            await self.database.execute(
                select(Claim.id, Claim.event_id).where(Claim.id.in_(claim_ids)).order_by(Claim.id)
            )
        ).all()
        if {claim_id for claim_id, _ in rows} != claim_ids:
            raise IntelligenceError("BASE_ANALYSIS_UNCONFLICTED_CLAIM_MISSING")
        return {event_id for _, event_id in rows}

    async def inputs(
        self, event_ids: set[UUID]
    ) -> tuple[list[EventBaseAnalysisInput], list[ExistingBaseAnalysisCandidate]]:
        if not event_ids:
            return [], []
        events = list(
            (
                await self.database.execute(
                    select(Event).where(Event.id.in_(event_ids)).order_by(Event.id)
                )
            ).scalars()
        )
        if {item.id for item in events} != event_ids:
            raise IntelligenceError("BASE_ANALYSIS_EVENT_MISSING")
        claims = list(
            (
                await self.database.execute(
                    select(Claim).where(Claim.event_id.in_(event_ids)).order_by(Claim.id)
                )
            ).scalars()
        )
        claim_events = {item.id: item.event_id for item in claims}
        claim_signal_rows = (
            (
                await self.database.execute(
                    select(ClaimSignal.claim_id, ClaimSignal.signal_id)
                    .where(ClaimSignal.claim_id.in_(claim_events))
                    .order_by(ClaimSignal.claim_id, ClaimSignal.signal_id)
                )
            ).all()
            if claims
            else []
        )
        claim_signals: dict[UUID, list[UUID]] = {item.id: [] for item in claims}
        claim_signal_pairs: set[tuple[UUID, UUID]] = set()
        for claim_id, signal_id in claim_signal_rows:
            claim_signals[claim_id].append(signal_id)
            claim_signal_pairs.add((claim_id, signal_id))

        event_signal_rows = (
            await self.database.execute(
                select(EventSignal.event_id, Signal)
                .join(Signal, Signal.id == EventSignal.signal_id)
                .where(EventSignal.event_id.in_(event_ids))
                .order_by(EventSignal.event_id, Signal.id)
            )
        ).all()
        event_signal_ids = {(event_id, signal.id) for event_id, signal in event_signal_rows}
        evidence_by_event: dict[UUID, list[ConflictEvidenceSignal]] = {
            event_id: [] for event_id in event_ids
        }
        for event_id, signal in event_signal_rows:
            evidence_by_event[event_id].append(self._evidence_signal(signal))
        if any(
            (claim_events[claim_id], signal_id) not in event_signal_ids
            for claim_id, signal_id in claim_signal_pairs
        ):
            raise IntelligenceError("BASE_ANALYSIS_CLAIM_EVIDENCE_INVALID")

        timeline = list(
            (
                await self.database.execute(
                    select(TimelineEntry)
                    .where(TimelineEntry.event_id.in_(event_ids))
                    .order_by(TimelineEntry.id)
                )
            ).scalars()
        )
        timeline_events = {item.id: item.event_id for item in timeline}
        timeline_claim_rows = (
            (
                await self.database.execute(
                    select(TimelineClaim.timeline_entry_id, TimelineClaim.claim_id)
                    .where(TimelineClaim.timeline_entry_id.in_(timeline_events))
                    .order_by(TimelineClaim.timeline_entry_id, TimelineClaim.claim_id)
                )
            ).all()
            if timeline
            else []
        )
        timeline_claims: dict[UUID, list[UUID]] = {item.id: [] for item in timeline}
        for timeline_id, claim_id in timeline_claim_rows:
            if claim_events.get(claim_id) != timeline_events[timeline_id]:
                raise IntelligenceError("BASE_ANALYSIS_TIMELINE_CLAIM_INVALID")
            timeline_claims[timeline_id].append(claim_id)

        conflicts = list(
            (
                await self.database.execute(
                    select(Conflict).where(Conflict.event_id.in_(event_ids)).order_by(Conflict.id)
                )
            ).scalars()
        )
        conflict_events = {item.id: item.event_id for item in conflicts}
        conflict_claim_rows = (
            (
                await self.database.execute(
                    select(ConflictClaim.conflict_id, ConflictClaim.claim_id)
                    .where(ConflictClaim.conflict_id.in_(conflict_events))
                    .order_by(ConflictClaim.conflict_id, ConflictClaim.claim_id)
                )
            ).all()
            if conflicts
            else []
        )
        conflict_signal_rows = (
            (
                await self.database.execute(
                    select(ConflictSignal.conflict_id, ConflictSignal.signal_id)
                    .where(ConflictSignal.conflict_id.in_(conflict_events))
                    .order_by(ConflictSignal.conflict_id, ConflictSignal.signal_id)
                )
            ).all()
            if conflicts
            else []
        )
        conflict_claims: dict[UUID, list[UUID]] = {item.id: [] for item in conflicts}
        conflict_signals: dict[UUID, list[UUID]] = {item.id: [] for item in conflicts}
        for conflict_id, claim_id in conflict_claim_rows:
            if claim_events.get(claim_id) != conflict_events[conflict_id]:
                raise IntelligenceError("BASE_ANALYSIS_CONFLICT_CLAIM_INVALID")
            conflict_claims[conflict_id].append(claim_id)
        for conflict_id, signal_id in conflict_signal_rows:
            event_id = conflict_events[conflict_id]
            if (event_id, signal_id) not in event_signal_ids or not any(
                (claim_id, signal_id) in claim_signal_pairs
                for claim_id in conflict_claims[conflict_id]
            ):
                raise IntelligenceError("BASE_ANALYSIS_CONFLICT_EVIDENCE_INVALID")
            conflict_signals[conflict_id].append(signal_id)

        candidates = list(
            (
                await self.database.execute(
                    select(BaseAnalysis)
                    .where(BaseAnalysis.event_id.in_(event_ids))
                    .order_by(BaseAnalysis.id)
                )
            ).scalars()
        )
        claims_by_event: dict[UUID, list[BaseAnalysisClaimInput]] = {
            event_id: [] for event_id in event_ids
        }
        timeline_by_event: dict[UUID, list[BaseAnalysisTimelineInput]] = {
            event_id: [] for event_id in event_ids
        }
        conflicts_by_event: dict[UUID, list[BaseAnalysisConflictInput]] = {
            event_id: [] for event_id in event_ids
        }
        for item in claims:
            claims_by_event[item.event_id].append(
                BaseAnalysisClaimInput(
                    claim_id=item.id,
                    text=item.text,
                    state=item.state,
                    evidence_signal_ids=claim_signals[item.id],
                )
            )
        for item in timeline:
            timeline_by_event[item.event_id].append(
                BaseAnalysisTimelineInput(
                    timeline_entry_id=item.id,
                    occurred_at=item.occurred_at,
                    summary=item.summary,
                    claim_ids=timeline_claims[item.id],
                )
            )
        for item in conflicts:
            conflicts_by_event[item.event_id].append(
                BaseAnalysisConflictInput(
                    conflict_id=item.id,
                    summary=item.summary,
                    claim_ids=conflict_claims[item.id],
                    evidence_signal_ids=conflict_signals[item.id],
                )
            )
        return (
            [
                EventBaseAnalysisInput(
                    event_id=item.id,
                    title=item.title,
                    overview=item.overview,
                    state=item.state,
                    display_time=item.display_time,
                    claims=claims_by_event[item.id],
                    timeline=timeline_by_event[item.id],
                    conflicts=conflicts_by_event[item.id],
                    evidence_signals=evidence_by_event[item.id],
                )
                for item in events
            ],
            [
                ExistingBaseAnalysisCandidate(
                    base_analysis_id=item.id,
                    event_id=item.event_id,
                    summary=item.summary,
                    event_type=item.event_type,
                    importance=item.importance,
                    topics=item.topics,
                    entities=item.entities,
                )
                for item in candidates
            ],
        )

    async def persist(
        self,
        *,
        run: PipelineRun,
        source_artifact_id: UUID,
        input_hash: str,
        response: BaseAnalysisResponse,
        candidates: dict[UUID, ExistingBaseAnalysisCandidate],
    ) -> tuple[int, int, int, bool]:
        assignments: list[BaseAnalysisAssignment] = []
        created = updated = 0
        for decision in response.payload.new_analyses:
            analysis_id = uuid4()
            self.database.add(
                BaseAnalysis(
                    id=analysis_id,
                    event_id=decision.event_id,
                    source_artifact_id=source_artifact_id,
                    summary=decision.summary,
                    event_type=decision.event_type,
                    importance=decision.importance,
                    topics=decision.topics,
                    entities=[item.model_dump(mode="json") for item in decision.entities],
                )
            )
            assignments.append(
                BaseAnalysisAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    base_analysis_id=analysis_id,
                    decision_type="new",
                )
            )
            created += 1
        for decision in response.payload.existing_analysis_updates:
            candidate = candidates.get(decision.existing_base_analysis_id)
            if candidate is None:
                raise IntelligenceError("BASE_ANALYSIS_OUTSIDE_CANDIDATES")
            analysis = await self.database.get(BaseAnalysis, decision.existing_base_analysis_id)
            if analysis is None or analysis.event_id != decision.event_id:
                raise IntelligenceError("BASE_ANALYSIS_EVENT_MISMATCH")
            analysis.source_artifact_id = source_artifact_id
            analysis.summary = decision.summary
            analysis.event_type = decision.event_type
            analysis.importance = decision.importance
            analysis.topics = decision.topics
            analysis.entities = [item.model_dump(mode="json") for item in decision.entities]
            assignments.append(
                BaseAnalysisAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    base_analysis_id=analysis.id,
                    decision_type="update",
                )
            )
            updated += 1
        artifact = BaseAnalysisArtifact(
            source_artifact_id=source_artifact_id,
            model_output=response.payload,
            assignments=assignments,
        )
        self.database.add(
            PipelineArtifact(
                id=uuid4(),
                pipeline_run_id=run.id,
                source_artifact_id=source_artifact_id,
                artifact_type=BASE_ANALYSIS_ARTIFACT,
                schema_version="base_analysis.v1",
                input_hash=input_hash,
                payload=artifact.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
        )
        return await self._commit_or_reuse(
            run, source_artifact_id, created, updated, 0, BASE_ANALYSIS_ARTIFACT
        )

    @staticmethod
    def _evidence_signal(signal: Signal) -> ConflictEvidenceSignal:
        if (
            signal.evidence_visibility == EvidenceVisibility.PRIVATE_SANITIZED.value
            and signal.public_provenance is not None
        ):
            raise IntelligenceError("INTELLIGENCE_PRIVATE_PROVENANCE_INVALID")
        return ConflictEvidenceSignal(
            signal_id=signal.id,
            published_at=signal.published_at,
            sanitized_text=signal.normalized_text,
            public_safe_provenance=signal.public_provenance,
        )


class BaseAnalysisRunner(IntelligenceRunnerBase):
    pipeline_name = BASE_ANALYSIS_PIPELINE
    artifact_type = BASE_ANALYSIS_ARTIFACT

    def __init__(
        self,
        *,
        repository: BaseAnalysisRepository,
        pipeline: PipelineRepository,
        client: BaseAnalysisClientProtocol,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(repository=repository, pipeline=pipeline, client=client, clock=clock)
        self.repository: BaseAnalysisRepository = repository
        self.client: BaseAnalysisClientProtocol = client

    def _validate_source(self, artifact: PipelineArtifact, run: PipelineRun) -> None:
        if (
            artifact.artifact_type != "conflict_analysis"
            or artifact.schema_version != "conflict_analysis.v1"
            or run.pipeline_name != "conflict_analysis"
            or run.status != PipelineRunStatus.SUCCEEDED.value
        ):
            raise IntelligenceError("BASE_ANALYSIS_SOURCE_INVALID")

    async def run(self, source_artifact_id: UUID) -> IntelligenceResult:
        source, source_run, run = await self._prepare(source_artifact_id)
        try:
            await self.repository.lock_source(source.id)
            if await self.repository.prior(self.artifact_type, source.id):
                return await self._reuse(run, source_run)
            try:
                parsed = ConflictAnalysisArtifact.model_validate(source.payload)
            except ValueError as error:
                raise IntelligenceError("BASE_ANALYSIS_SOURCE_SCHEMA_INVALID") from error
            event_ids = await self._source_event_ids(parsed)
            events, candidates = await self.repository.inputs(event_ids)
            response = await self._response(events, candidates)
            self._validate(response.payload, events, candidates)
            created, updated, attached, reused = await self.repository.persist(
                run=run,
                source_artifact_id=source.id,
                input_hash=self._input_hash(source, events, candidates),
                response=response,
                candidates={item.base_analysis_id: item for item in candidates},
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

    async def _source_event_ids(self, artifact: ConflictAnalysisArtifact) -> set[UUID]:
        decisions = [
            *artifact.model_output.new_conflicts,
            *artifact.model_output.existing_conflict_updates,
        ]
        event_ids = {item.event_id for item in decisions}
        event_ids.update(
            await self.repository.event_ids_for_unconflicted_claims(
                set(artifact.model_output.unconflicted_claim_ids)
            )
        )
        return event_ids

    async def _response(
        self,
        events: list[EventBaseAnalysisInput],
        candidates: list[ExistingBaseAnalysisCandidate],
    ) -> BaseAnalysisResponse:
        if not events:
            return BaseAnalysisResponse(
                payload=BaseAnalysisPayload(new_analyses=[], existing_analysis_updates=[]),
                provider="backend",
                model="no-op",
                token_usage=TokenUsage(),
            )
        return await self.client.analyze_base(events=events, candidates=candidates)

    @staticmethod
    def _validate(
        payload: BaseAnalysisPayload,
        events: list[EventBaseAnalysisInput],
        candidates: list[ExistingBaseAnalysisCandidate],
    ) -> None:
        expected_event_ids = {item.event_id for item in events}
        new_event_ids = {item.event_id for item in payload.new_analyses}
        updated_event_ids = {item.event_id for item in payload.existing_analysis_updates}
        if new_event_ids | updated_event_ids != expected_event_ids:
            raise IntelligenceError("BASE_ANALYSIS_EVENT_COVERAGE_INVALID")
        candidates_by_id = {item.base_analysis_id: item for item in candidates}
        candidates_by_event = {item.event_id: item for item in candidates}
        if any(event_id in candidates_by_event for event_id in new_event_ids):
            raise IntelligenceError("BASE_ANALYSIS_NEW_HAS_CANDIDATE")
        for item in payload.existing_analysis_updates:
            candidate = candidates_by_id.get(item.existing_base_analysis_id)
            if candidate is None or candidate.event_id != item.event_id:
                raise IntelligenceError("BASE_ANALYSIS_OUTSIDE_CANDIDATES")
        if updated_event_ids != set(candidates_by_event):
            raise IntelligenceError("BASE_ANALYSIS_CANDIDATE_COVERAGE_INVALID")
