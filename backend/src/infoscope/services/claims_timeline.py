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
    ConflictAnalysisArtifact,
    ConflictAnalysisPayload,
    ConflictAnalysisResponse,
    ConflictAssignment,
    ConflictClaimInput,
    ConflictEvidenceSignal,
    EventClaimInput,
    EventConflictInput,
    EventTimelineInput,
    ExistingClaimCandidate,
    ExistingConflictCandidate,
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
from infoscope.pipeline import AcquisitionCursor, LogicalWindow
from infoscope.services.pipeline import PipelineRepository

logger = logging.getLogger("infoscope.pipeline.claims_timeline")
CLAIM_PIPELINE = "claim_extraction"
CLAIM_ARTIFACT = "claim_extraction"
TIMELINE_PIPELINE = "timeline_reconstruction"
TIMELINE_ARTIFACT = "timeline_reconstruction"
CONFLICT_PIPELINE = "conflict_analysis"
CONFLICT_ARTIFACT = "conflict_analysis"
CLAIM_STATES = {"confirmed", "unresolved", "conflicting", "contradicted"}
EVENT_STATES = {"developing", "confirmed", "conflicting", "cooling"}


class IntelligenceClientProtocol(Protocol):
    async def extract_claims(
        self, *, events: list[EventClaimInput], candidates: list[ExistingClaimCandidate]
    ) -> ClaimExtractionResponse: ...

    async def reconstruct_timeline(
        self, *, events: list[EventTimelineInput], candidates: list[ExistingTimelineCandidate]
    ) -> TimelineReconstructionResponse: ...

    async def analyze_conflicts(
        self, *, events: list[EventConflictInput], candidates: list[ExistingConflictCandidate]
    ) -> ConflictAnalysisResponse: ...


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
        self, event_ids: set[UUID], *, signal_ids: list[UUID] | None = None
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
        signal_query = (
            select(EventSignal.event_id, Signal)
            .join(Signal, Signal.id == EventSignal.signal_id)
            .where(EventSignal.event_id.in_(event_ids))
        )
        if signal_ids is not None:
            signal_query = signal_query.where(EventSignal.signal_id.in_(signal_ids))
        rows = (
            (
                await self.database.execute(signal_query)
            ).all()
            if event_ids
            else []
        )
        signals: dict[UUID, list[AnalysisSignal]] = {event_id: [] for event_id in event_ids}
        if signal_ids is None:
            for event_id, signal in rows:
                signals[event_id].append(self._analysis_signal(signal))
        else:
            by_signal_id = {signal.id: (event_id, signal) for event_id, signal in rows}
            if set(by_signal_id) != set(signal_ids):
                raise IntelligenceError("CLAIM_INCREMENTAL_SIGNAL_MISSING")
            for signal_id in signal_ids:
                event_id, signal = by_signal_id[signal_id]
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

    async def event_ids_for_claims(self, claim_ids: set[UUID]) -> set[UUID]:
        if not claim_ids:
            return set()
        rows = (
            await self.database.execute(
                select(Claim.id, Claim.event_id).where(Claim.id.in_(claim_ids))
            )
        ).all()
        if {claim_id for claim_id, _ in rows} != claim_ids:
            raise IntelligenceError("CONFLICT_CLAIM_MISSING")
        return {event_id for _, event_id in rows}

    async def conflict_inputs(
        self, event_ids: set[UUID]
    ) -> tuple[list[EventConflictInput], list[ExistingConflictCandidate]]:
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
            raise IntelligenceError("CONFLICT_EVENT_MISSING")
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
                    select(ClaimSignal.claim_id, Signal)
                    .join(Signal, Signal.id == ClaimSignal.signal_id)
                    .where(ClaimSignal.claim_id.in_([item.id for item in claims]))
                )
            ).all()
            if claims
            else []
        )
        event_signal_rows = (
            (
                await self.database.execute(
                    select(EventSignal.event_id, EventSignal.signal_id).where(
                        EventSignal.event_id.in_(event_ids)
                    )
                )
            ).all()
            if event_ids
            else []
        )
        event_signals = {(event_id, signal_id) for event_id, signal_id in event_signal_rows}
        claim_events = {item.id: item.event_id for item in claims}
        evidence: dict[UUID, list[ConflictEvidenceSignal]] = {item.id: [] for item in claims}
        claim_signal_ids: set[tuple[UUID, UUID]] = set()
        for claim_id, signal in claim_links:
            if (claim_events[claim_id], signal.id) not in event_signals:
                raise IntelligenceError("CONFLICT_EVIDENCE_OUTSIDE_EVENT")
            claim_signal_ids.add((claim_id, signal.id))
            evidence[claim_id].append(self._conflict_signal(signal))

        conflicts = (
            list(
                (
                    await self.database.execute(
                        select(Conflict).where(Conflict.event_id.in_(event_ids))
                    )
                ).scalars()
            )
            if event_ids
            else []
        )
        conflict_ids = [item.id for item in conflicts]
        conflict_claim_rows = (
            (
                await self.database.execute(
                    select(ConflictClaim.conflict_id, ConflictClaim.claim_id).where(
                        ConflictClaim.conflict_id.in_(conflict_ids)
                    )
                )
            ).all()
            if conflict_ids
            else []
        )
        conflict_signal_rows = (
            (
                await self.database.execute(
                    select(ConflictSignal.conflict_id, ConflictSignal.signal_id).where(
                        ConflictSignal.conflict_id.in_(conflict_ids)
                    )
                )
            ).all()
            if conflict_ids
            else []
        )
        linked_claims: dict[UUID, list[UUID]] = {item.id: [] for item in conflicts}
        linked_signals: dict[UUID, list[UUID]] = {item.id: [] for item in conflicts}
        conflict_events = {item.id: item.event_id for item in conflicts}
        for conflict_id, claim_id in conflict_claim_rows:
            if claim_events.get(claim_id) != conflict_events[conflict_id]:
                raise IntelligenceError("CONFLICT_CANDIDATE_CLAIM_INVALID")
            linked_claims[conflict_id].append(claim_id)
        for conflict_id, signal_id in conflict_signal_rows:
            if (conflict_events[conflict_id], signal_id) not in event_signals or not any(
                (claim_id, signal_id) in claim_signal_ids for claim_id in linked_claims[conflict_id]
            ):
                raise IntelligenceError("CONFLICT_CANDIDATE_EVIDENCE_INVALID")
            linked_signals[conflict_id].append(signal_id)
        if any(not linked_claims[item.id] for item in conflicts):
            raise IntelligenceError("CONFLICT_CANDIDATE_CLAIM_INVALID")

        claims_by_event: dict[UUID, list[ConflictClaimInput]] = {
            event_id: [] for event_id in event_ids
        }
        for item in claims:
            claims_by_event[item.event_id].append(
                ConflictClaimInput(
                    claim_id=item.id,
                    event_id=item.event_id,
                    text=item.text,
                    state=item.state,
                    evidence_signals=evidence[item.id],
                )
            )
        return (
            [
                EventConflictInput(
                    event_id=item.id,
                    title=item.title,
                    overview=item.overview,
                    state=item.state,
                    claims=claims_by_event[item.id],
                )
                for item in events
            ],
            [
                ExistingConflictCandidate(
                    conflict_id=item.id,
                    event_id=item.event_id,
                    summary=item.summary,
                    claim_ids=linked_claims[item.id],
                    evidence_signal_ids=linked_signals[item.id],
                )
                for item in conflicts
            ],
        )

    async def timeline_inputs(
        self, event_ids: set[UUID]
    ) -> tuple[list[EventTimelineInput], list[ExistingTimelineCandidate]]:
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
            raise IntelligenceError("TIMELINE_EVENT_MISSING")
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
                    select(ClaimSignal.claim_id, Signal)
                    .join(Signal, Signal.id == ClaimSignal.signal_id)
                    .where(ClaimSignal.claim_id.in_([item.id for item in claims]))
                )
            ).all()
            if claims
            else []
        )
        event_signal_rows = (
            (
                await self.database.execute(
                    select(EventSignal.event_id, EventSignal.signal_id).where(
                        EventSignal.event_id.in_(event_ids)
                    )
                )
            ).all()
            if event_ids
            else []
        )
        event_signals = {(event_id, signal_id) for event_id, signal_id in event_signal_rows}
        claim_events = {item.id: item.event_id for item in claims}
        evidence: dict[UUID, list[AnalysisSignal]] = {item.id: [] for item in claims}
        for claim_id, signal in claim_links:
            if (claim_events[claim_id], signal.id) not in event_signals:
                raise IntelligenceError("TIMELINE_EVIDENCE_OUTSIDE_EVENT")
            evidence[claim_id].append(self._analysis_signal(signal))
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
        claims_by_event: dict[UUID, list[ClaimTimelineInput]] = {
            event_id: [] for event_id in event_ids
        }
        for item in claims:
            claims_by_event[item.event_id].append(
                ClaimTimelineInput(
                    claim_id=item.id,
                    event_id=item.event_id,
                    text=item.text,
                    state=item.state,
                    evidence_signals=evidence[item.id],
                )
            )
        return (
            [
                EventTimelineInput(
                    event_id=item.id,
                    title=item.title,
                    overview=item.overview,
                    state=item.state,
                    display_time=item.display_time,
                    claims=claims_by_event[item.id],
                )
                for item in events
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

    async def persist_conflicts(
        self,
        *,
        run: PipelineRun,
        source_artifact_id: UUID,
        input_hash: str,
        response: ConflictAnalysisResponse,
        candidates: dict[UUID, ExistingConflictCandidate],
    ) -> tuple[int, int, int, bool]:
        assignments: list[ConflictAssignment] = []
        affected_claims: dict[UUID, set[UUID]] = {}
        created = updated = attached = 0
        for decision in response.payload.new_conflicts:
            conflict_id = uuid4()
            self.database.add(
                Conflict(
                    id=conflict_id,
                    event_id=decision.event_id,
                    summary=decision.summary,
                )
            )
            assignments.append(
                ConflictAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    conflict_id=conflict_id,
                    decision_type="new",
                )
            )
            attached += await self._attach_conflict_claims(conflict_id, decision.claim_ids, run.id)
            attached += await self._attach_conflict_signals(
                conflict_id, decision.evidence_signal_ids, run.id
            )
            affected_claims.setdefault(decision.event_id, set()).update(decision.claim_ids)
            created += 1
        for decision in response.payload.existing_conflict_updates:
            candidate = candidates.get(decision.existing_conflict_id)
            if candidate is None:
                raise IntelligenceError("CONFLICT_OUTSIDE_CANDIDATES")
            conflict = await self.database.get(Conflict, decision.existing_conflict_id)
            if conflict is None or conflict.event_id != decision.event_id:
                raise IntelligenceError("CONFLICT_EVENT_MISMATCH")
            conflict.summary = decision.summary
            assignments.append(
                ConflictAssignment(
                    decision_key=decision.decision_key,
                    event_id=decision.event_id,
                    conflict_id=conflict.id,
                    decision_type="update",
                )
            )
            attached += await self._attach_conflict_claims(conflict.id, decision.claim_ids, run.id)
            attached += await self._attach_conflict_signals(
                conflict.id, decision.evidence_signal_ids, run.id
            )
            affected_claims.setdefault(decision.event_id, set()).update(
                [*candidate.claim_ids, *decision.claim_ids]
            )
            updated += 1
        await self._apply_conflict_states(affected_claims)
        payload = ConflictAnalysisArtifact(
            source_artifact_id=source_artifact_id,
            model_output=response.payload,
            assignments=assignments,
        )
        self.database.add(
            PipelineArtifact(
                id=uuid4(),
                pipeline_run_id=run.id,
                source_artifact_id=source_artifact_id,
                artifact_type=CONFLICT_ARTIFACT,
                schema_version="conflict_analysis.v1",
                input_hash=input_hash,
                payload=payload.model_dump(mode="json"),
                provider=response.provider,
                model=response.model,
                token_usage=response.token_usage.model_dump(mode="json"),
            )
        )
        return await self._commit_or_reuse(
            run, source_artifact_id, created, updated, attached, CONFLICT_ARTIFACT
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

    async def _attach_conflict_claims(
        self, conflict_id: UUID, claim_ids: list[UUID], run_id: UUID
    ) -> int:
        result = await self.database.execute(
            insert(ConflictClaim)
            .values(
                [
                    {
                        "id": uuid4(),
                        "conflict_id": conflict_id,
                        "claim_id": value,
                        "attached_by_pipeline_run_id": run_id,
                    }
                    for value in claim_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[ConflictClaim.conflict_id, ConflictClaim.claim_id]
            )
            .returning(ConflictClaim.id)
        )
        return len(list(result.scalars()))

    async def _attach_conflict_signals(
        self, conflict_id: UUID, signal_ids: list[UUID], run_id: UUID
    ) -> int:
        if not signal_ids:
            return 0
        result = await self.database.execute(
            insert(ConflictSignal)
            .values(
                [
                    {
                        "id": uuid4(),
                        "conflict_id": conflict_id,
                        "signal_id": value,
                        "attached_by_pipeline_run_id": run_id,
                    }
                    for value in signal_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[ConflictSignal.conflict_id, ConflictSignal.signal_id]
            )
            .returning(ConflictSignal.id)
        )
        return len(list(result.scalars()))

    async def _apply_conflict_states(self, affected_claims: dict[UUID, set[UUID]]) -> None:
        for event_id, claim_ids in affected_claims.items():
            event = await self.database.get(Event, event_id)
            if event is None:
                raise IntelligenceError("CONFLICT_EVENT_MISSING")
            if event.state not in EVENT_STATES:
                raise IntelligenceError("CONFLICT_EVENT_STATE_INVALID")
            claims = list(
                (
                    await self.database.execute(select(Claim).where(Claim.id.in_(claim_ids)))
                ).scalars()
            )
            if {item.id for item in claims} != claim_ids:
                raise IntelligenceError("CONFLICT_CLAIM_MISSING")
            if any(item.event_id != event_id or item.state not in CLAIM_STATES for item in claims):
                raise IntelligenceError("CONFLICT_CLAIM_STATE_INVALID")
            for claim in claims:
                if claim.state in {"confirmed", "unresolved"}:
                    claim.state = "conflicting"
            event.state = "conflicting"

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

    @staticmethod
    def _conflict_signal(signal: Signal) -> ConflictEvidenceSignal:
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


class IntelligenceRunnerBase:
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


class ClaimExtractionRunner(IntelligenceRunnerBase):
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
            assigned_signal_ids = [
                signal_id
                for decision in [
                    *parsed.model_output.new_events,
                    *parsed.model_output.existing_event_updates,
                ]
                for signal_id in decision.signal_ids
            ]
            events, candidates = await self.repository.claim_inputs(
                event_ids, signal_ids=assigned_signal_ids
            )
            response = await self.client.extract_claims(events=events, candidates=candidates)
            response = self._normalize_decisions(response, events, candidates)
            response = self._normalize_coverage(response, events)
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
    def _normalize_decisions(
        response: ClaimExtractionResponse,
        events: list[EventClaimInput],
        candidates: list[ExistingClaimCandidate],
    ) -> ClaimExtractionResponse:
        current_by_event = {
            event.event_id: {signal.signal_id for signal in event.signals}
            for event in events
        }
        candidates_by_id = {candidate.claim_id: candidate for candidate in candidates}
        new_claims = []
        dropped = filtered = 0
        for decision in response.payload.new_claims:
            current = current_by_event.get(decision.event_id)
            if current is None:
                new_claims.append(decision)
                continue
            evidence = [
                signal_id
                for signal_id in decision.evidence_signal_ids
                if signal_id in current
            ]
            if not evidence:
                dropped += 1
                continue
            if evidence != decision.evidence_signal_ids:
                filtered += 1
                decision = decision.model_copy(update={"evidence_signal_ids": evidence})
            new_claims.append(decision)

        updates = []
        for decision in response.payload.existing_claim_updates:
            candidate = candidates_by_id.get(decision.existing_claim_id)
            current = current_by_event.get(decision.event_id)
            if current is None:
                updates.append(decision)
                continue
            if candidate is None or candidate.event_id != decision.event_id:
                dropped += 1
                continue
            allowed = current | set(candidate.evidence_signal_ids)
            evidence = [
                signal_id
                for signal_id in decision.evidence_signal_ids
                if signal_id in allowed
            ]
            if not set(evidence) & current:
                dropped += 1
                continue
            if evidence != decision.evidence_signal_ids:
                filtered += 1
                decision = decision.model_copy(update={"evidence_signal_ids": evidence})
            updates.append(decision)

        if dropped or filtered:
            logger.warning(
                "pipeline claim decisions normalized dropped=%d filtered=%d",
                dropped,
                filtered,
            )
        return response.model_copy(
            update={
                "payload": response.payload.model_copy(
                    update={
                        "new_claims": new_claims,
                        "existing_claim_updates": updates,
                    }
                )
            }
        )

    @staticmethod
    def _normalize_coverage(
        response: ClaimExtractionResponse, events: list[EventClaimInput]
    ) -> ClaimExtractionResponse:
        decisions = [
            *response.payload.new_claims,
            *response.payload.existing_claim_updates,
        ]
        supplied = {
            signal.signal_id for event in events for signal in event.signals
        }
        used = {
            value
            for item in decisions
            for value in item.evidence_signal_ids
            if value in supplied
        }
        unused = [
            signal.signal_id
            for event in events
            for signal in event.signals
            if signal.signal_id not in used
        ]
        if unused != response.payload.unused_signal_ids:
            logger.info(
                "pipeline coverage normalized pipeline=%s supplied=%d used=%d unused=%d",
                CLAIM_PIPELINE,
                len(used) + len(unused),
                len(used),
                len(unused),
            )
        return response.model_copy(
            update={
                "payload": response.payload.model_copy(
                    update={"unused_signal_ids": unused}
                )
            }
        )

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
        for item in payload.new_claims:
            if item.event_id not in event_signals or not set(item.evidence_signal_ids) <= (
                event_signals[item.event_id]
            ):
                raise IntelligenceError("CLAIM_EVIDENCE_INVALID")
        by_id = {item.claim_id: item for item in candidates}
        for item in payload.existing_claim_updates:
            candidate = by_id.get(item.existing_claim_id)
            if candidate is None or candidate.event_id != item.event_id:
                raise IntelligenceError("CLAIM_OUTSIDE_CANDIDATES")
            allowed = event_signals.get(item.event_id, set()) | set(
                candidate.evidence_signal_ids
            )
            if not set(item.evidence_signal_ids) <= allowed:
                raise IntelligenceError("CLAIM_EVIDENCE_INVALID")
        current_used = {
            value
            for item in [*payload.new_claims, *payload.existing_claim_updates]
            for value in item.evidence_signal_ids
            if value in expected
        }
        if current_used | set(payload.unused_signal_ids) != expected:
            raise IntelligenceError("CLAIM_SIGNAL_COVERAGE_INVALID")


class TimelineReconstructionRunner(IntelligenceRunnerBase):
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
            events, candidates = await self.repository.timeline_inputs(event_ids)
            response = await self.client.reconstruct_timeline(events=events, candidates=candidates)
            response = self._normalize_decisions(response, events, candidates)
            response = self._normalize_coverage(response, events)
            self._validate(response.payload, events, candidates)
            created, updated, attached, reused = await self.repository.persist_timeline(
                run=run,
                source_artifact_id=source.id,
                input_hash=self._input_hash(source, events, candidates),
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
    def _normalize_decisions(
        response: TimelineReconstructionResponse,
        events: list[EventTimelineInput],
        candidates: list[ExistingTimelineCandidate],
    ) -> TimelineReconstructionResponse:
        claims_by_event = {
            event.event_id: {claim.claim_id for claim in event.claims}
            for event in events
        }
        candidates_by_id = {
            candidate.timeline_entry_id: candidate for candidate in candidates
        }
        new_entries = []
        updates = []
        dropped = filtered = 0
        for decision in response.payload.new_entries:
            allowed = claims_by_event.get(decision.event_id)
            if allowed is None:
                new_entries.append(decision)
                continue
            claim_ids = [claim_id for claim_id in decision.claim_ids if claim_id in allowed]
            if not claim_ids:
                dropped += 1
                continue
            if claim_ids != decision.claim_ids:
                filtered += 1
                decision = decision.model_copy(update={"claim_ids": claim_ids})
            new_entries.append(decision)
        for decision in response.payload.existing_entry_updates:
            candidate = candidates_by_id.get(decision.existing_timeline_entry_id)
            allowed = claims_by_event.get(decision.event_id)
            if candidate is None or allowed is None or candidate.event_id != decision.event_id:
                updates.append(decision)
                continue
            claim_ids = [claim_id for claim_id in decision.claim_ids if claim_id in allowed]
            if not claim_ids:
                dropped += 1
                continue
            if claim_ids != decision.claim_ids:
                filtered += 1
                decision = decision.model_copy(update={"claim_ids": claim_ids})
            updates.append(decision)
        if dropped or filtered:
            logger.warning(
                "pipeline timeline decisions normalized dropped=%d filtered=%d",
                dropped,
                filtered,
            )
        return response.model_copy(
            update={
                "payload": response.payload.model_copy(
                    update={
                        "new_entries": new_entries,
                        "existing_entry_updates": updates,
                    }
                )
            }
        )

    @staticmethod
    def _normalize_coverage(
        response: TimelineReconstructionResponse, events: list[EventTimelineInput]
    ) -> TimelineReconstructionResponse:
        decisions = [
            *response.payload.new_entries,
            *response.payload.existing_entry_updates,
        ]
        used = {value for item in decisions for value in item.claim_ids}
        unused = [
            claim.claim_id
            for event in events
            for claim in event.claims
            if claim.claim_id not in used
        ]
        if unused != response.payload.unused_claim_ids:
            logger.info(
                "pipeline coverage normalized pipeline=%s supplied=%d used=%d unused=%d",
                TIMELINE_PIPELINE,
                len(used) + len(unused),
                len(used),
                len(unused),
            )
        return response.model_copy(
            update={
                "payload": response.payload.model_copy(
                    update={"unused_claim_ids": unused}
                )
            }
        )

    @staticmethod
    def _validate(
        payload: TimelineReconstructionPayload,
        events: list[EventTimelineInput],
        candidates: list[ExistingTimelineCandidate],
    ) -> None:
        claim_events = {claim.claim_id: item.event_id for item in events for claim in item.claims}
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


class ConflictAnalysisRunner(IntelligenceRunnerBase):
    pipeline_name = CONFLICT_PIPELINE
    artifact_type = CONFLICT_ARTIFACT

    def _validate_source(self, artifact: PipelineArtifact, run: PipelineRun) -> None:
        if (
            artifact.artifact_type != TIMELINE_ARTIFACT
            or artifact.schema_version != "timeline_reconstruction.v1"
            or run.pipeline_name != TIMELINE_PIPELINE
            or run.status != PipelineRunStatus.SUCCEEDED.value
        ):
            raise IntelligenceError("CONFLICT_SOURCE_INVALID")

    async def run(self, source_artifact_id: UUID) -> IntelligenceResult:
        source, source_run, run = await self._prepare(source_artifact_id)
        try:
            await self.repository.lock_source(source.id)
            if await self.repository.prior(self.artifact_type, source.id):
                return await self._reuse(run, source_run)
            try:
                parsed = TimelineReconstructionArtifact.model_validate(source.payload)
            except ValueError as error:
                raise IntelligenceError("CONFLICT_SOURCE_SCHEMA_INVALID") from error
            decisions = [
                *parsed.model_output.new_entries,
                *parsed.model_output.existing_entry_updates,
            ]
            claim_ids = {value for decision in decisions for value in decision.claim_ids} | set(
                parsed.model_output.unused_claim_ids
            )
            event_ids = await self.repository.event_ids_for_claims(claim_ids)
            event_ids.update(item.event_id for item in parsed.assignments)
            events, candidates = await self.repository.conflict_inputs(event_ids)
            response = await self.client.analyze_conflicts(events=events, candidates=candidates)
            response = self._normalize_decisions(response, events, candidates)
            response = self._normalize_coverage(response, events)
            self._validate(response.payload, events, candidates)
            candidate_map = {item.conflict_id: item for item in candidates}
            created, updated, attached, reused = await self.repository.persist_conflicts(
                run=run,
                source_artifact_id=source.id,
                input_hash=self._input_hash(source, events, candidates),
                response=response,
                candidates=candidate_map,
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
    def _normalize_decisions(
        response: ConflictAnalysisResponse,
        events: list[EventConflictInput],
        candidates: list[ExistingConflictCandidate],
    ) -> ConflictAnalysisResponse:
        claims_by_event = {
            event.event_id: {claim.claim_id for claim in event.claims}
            for event in events
        }
        evidence_by_claim = {
            claim.claim_id: {signal.signal_id for signal in claim.evidence_signals}
            for event in events
            for claim in event.claims
        }
        candidates_by_id = {candidate.conflict_id: candidate for candidate in candidates}

        def normalized_relations(decision):
            allowed_claims = claims_by_event.get(decision.event_id)
            if allowed_claims is None:
                return None
            claim_ids = [
                claim_id for claim_id in decision.claim_ids if claim_id in allowed_claims
            ]
            allowed_evidence = set().union(
                *(evidence_by_claim[claim_id] for claim_id in claim_ids)
            ) if claim_ids else set()
            evidence_ids = [
                signal_id
                for signal_id in decision.evidence_signal_ids
                if signal_id in allowed_evidence
            ]
            return claim_ids, evidence_ids

        new_conflicts = []
        updates = []
        dropped = filtered = 0
        for decision in response.payload.new_conflicts:
            relations = normalized_relations(decision)
            if relations is None:
                new_conflicts.append(decision)
                continue
            claim_ids, evidence_ids = relations
            if not claim_ids or (len(claim_ids) == 1 and not evidence_ids):
                dropped += 1
                continue
            if (
                claim_ids != decision.claim_ids
                or evidence_ids != decision.evidence_signal_ids
            ):
                filtered += 1
                decision = decision.model_copy(
                    update={
                        "claim_ids": claim_ids,
                        "evidence_signal_ids": evidence_ids,
                    }
                )
            new_conflicts.append(decision)
        for decision in response.payload.existing_conflict_updates:
            candidate = candidates_by_id.get(decision.existing_conflict_id)
            relations = normalized_relations(decision)
            if candidate is None or relations is None or candidate.event_id != decision.event_id:
                updates.append(decision)
                continue
            claim_ids, evidence_ids = relations
            if not claim_ids and not evidence_ids:
                dropped += 1
                continue
            if (
                claim_ids != decision.claim_ids
                or evidence_ids != decision.evidence_signal_ids
            ):
                filtered += 1
                decision = decision.model_copy(
                    update={
                        "claim_ids": claim_ids,
                        "evidence_signal_ids": evidence_ids,
                    }
                )
            updates.append(decision)
        if dropped or filtered:
            logger.warning(
                "pipeline conflict decisions normalized dropped=%d filtered=%d",
                dropped,
                filtered,
            )
        return response.model_copy(
            update={
                "payload": response.payload.model_copy(
                    update={
                        "new_conflicts": new_conflicts,
                        "existing_conflict_updates": updates,
                    }
                )
            }
        )

    @staticmethod
    def _normalize_coverage(
        response: ConflictAnalysisResponse, events: list[EventConflictInput]
    ) -> ConflictAnalysisResponse:
        decisions = [
            *response.payload.new_conflicts,
            *response.payload.existing_conflict_updates,
        ]
        used = {value for item in decisions for value in item.claim_ids}
        unconflicted = [
            claim.claim_id
            for event in events
            for claim in event.claims
            if claim.claim_id not in used
        ]
        if unconflicted != response.payload.unconflicted_claim_ids:
            logger.info(
                "pipeline coverage normalized pipeline=%s supplied=%d used=%d unconflicted=%d",
                CONFLICT_PIPELINE,
                len(used) + len(unconflicted),
                len(used),
                len(unconflicted),
            )
        return response.model_copy(
            update={
                "payload": response.payload.model_copy(
                    update={"unconflicted_claim_ids": unconflicted}
                )
            }
        )

    @staticmethod
    def _validate(
        payload: ConflictAnalysisPayload,
        events: list[EventConflictInput],
        candidates: list[ExistingConflictCandidate],
    ) -> None:
        claim_events = {claim.claim_id: item.event_id for item in events for claim in item.claims}
        evidence_by_claim = {
            claim.claim_id: {signal.signal_id for signal in claim.evidence_signals}
            for item in events
            for claim in item.claims
        }
        decisions = [*payload.new_conflicts, *payload.existing_conflict_updates]
        for item in decisions:
            if any(claim_events.get(claim_id) != item.event_id for claim_id in item.claim_ids):
                raise IntelligenceError("CONFLICT_CLAIM_INVALID")
            allowed_evidence = set().union(
                *(evidence_by_claim[claim_id] for claim_id in item.claim_ids)
            )
            if not set(item.evidence_signal_ids) <= allowed_evidence:
                raise IntelligenceError("CONFLICT_EVIDENCE_INVALID")
        used_claim_ids = {value for item in decisions for value in item.claim_ids}
        if used_claim_ids | set(payload.unconflicted_claim_ids) != set(claim_events):
            raise IntelligenceError("CONFLICT_CLAIM_COVERAGE_INVALID")

        by_id = {item.conflict_id: item for item in candidates}
        for item in payload.existing_conflict_updates:
            candidate = by_id.get(item.existing_conflict_id)
            if candidate is None or candidate.event_id != item.event_id:
                raise IntelligenceError("CONFLICT_OUTSIDE_CANDIDATES")
            effective_claims = set(candidate.claim_ids) | set(item.claim_ids)
            effective_evidence = set(candidate.evidence_signal_ids) | set(item.evidence_signal_ids)
            if len(effective_claims) == 1 and not effective_evidence:
                raise IntelligenceError("CONFLICT_STRUCTURE_INVALID")
