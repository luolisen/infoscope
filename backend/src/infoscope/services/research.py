from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.integrations.research.fetcher import (
    FetchedResearchSource,
    ResearchFetchError,
)
from infoscope.integrations.research.schemas import (
    ResearchClaim,
    ResearchConflict,
    ResearchDiscovery,
    ResearchDiscoveryAudit,
    ResearchDiscoveryAuditCandidate,
    ResearchDiscoveryResponse,
    ResearchEvent,
    ResearchEvidence,
    ResearchFactSnapshot,
    ResearchProvenance,
    ResearchRequestPayload,
    ResearchRequestSpec,
    ResearchTimeline,
    TelegramPublicProvenance,
    TrendRadarProvenance,
    canonical_json_bytes,
    request_input_hash,
)
from infoscope.integrations.research.url_policy import (
    ResearchURLRejected,
    ValidatedURL,
    validate_public_url,
)
from infoscope.models import (
    EvidenceVisibility,
    ResearchDiscoveryArtifact,
    ResearchRequest,
    ResearchRequestEvent,
    ResearchRun,
    ResearchSource,
    ResearchSourceKind,
    ResearchSourceStatus,
    ResearchStatus,
    ResearchTrigger,
    Signal,
    SourceVisibility,
)
from infoscope.services.acquisition import AcquisitionRepository, RawInformationInput
from infoscope.services.base_analysis import BaseAnalysisRepository


class ResearchError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ResearchCandidateAudit:
    candidate_index: int
    source_kind: ResearchSourceKind
    candidate_url_hash: str
    status: ResearchSourceStatus
    canonical_url: str | None = None
    canonical_url_hash: str | None = None
    error_code: str | None = None


class ResearchDiscoveryClient(Protocol):
    async def discover(
        self, payload: ResearchRequestPayload, *, workdir: Path
    ) -> ResearchDiscoveryResponse: ...


class ResearchFetcher(Protocol):
    async def fetch(
        self, source_kind, validated: ValidatedURL
    ) -> FetchedResearchSource: ...


class URLValidator(Protocol):
    async def __call__(self, value: str, source_kind) -> ValidatedURL: ...


class ResearchHealthChecker(Protocol):
    async def check(self) -> None: ...


class ResearchRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def fact_snapshot(self, event_ids: set[UUID]) -> ResearchFactSnapshot:
        inputs, _candidates = await BaseAnalysisRepository(self.database).inputs(event_ids)
        signal_ids = {
            evidence.signal_id for event in inputs for evidence in event.evidence_signals
        }
        signals = list(
            (
                await self.database.execute(
                    select(Signal).where(Signal.id.in_(signal_ids)).order_by(Signal.id)
                )
            ).scalars()
        )
        signal_map = {item.id: item for item in signals}
        if set(signal_map) != signal_ids:
            raise ResearchError("RESEARCH_FACT_SNAPSHOT_INVALID")
        events: list[ResearchEvent] = []
        for event in inputs:
            evidence = [
                self._evidence(signal_map[item.signal_id])
                for item in sorted(event.evidence_signals, key=lambda value: value.signal_id)
            ]
            events.append(
                ResearchEvent(
                    event_id=event.event_id,
                    title=event.title,
                    overview=event.overview,
                    state=event.state,
                    display_time=event.display_time,
                    claims=[
                        ResearchClaim(
                            claim_id=item.claim_id,
                            text=item.text,
                            state=item.state,
                            evidence_signal_ids=sorted(item.evidence_signal_ids),
                        )
                        for item in sorted(event.claims, key=lambda value: value.claim_id)
                    ],
                    timeline=[
                        ResearchTimeline(
                            timeline_entry_id=item.timeline_entry_id,
                            occurred_at=item.occurred_at,
                            summary=item.summary,
                            claim_ids=sorted(item.claim_ids),
                        )
                        for item in sorted(
                            event.timeline, key=lambda value: value.timeline_entry_id
                        )
                    ],
                    conflicts=[
                        ResearchConflict(
                            conflict_id=item.conflict_id,
                            summary=item.summary,
                            claim_ids=sorted(item.claim_ids),
                            evidence_signal_ids=sorted(item.evidence_signal_ids),
                        )
                        for item in sorted(event.conflicts, key=lambda value: value.conflict_id)
                    ],
                    evidence_signals=evidence,
                )
            )
        snapshot = ResearchFactSnapshot(events=sorted(events, key=lambda item: item.event_id))
        if len(canonical_json_bytes(snapshot)) > 100_000:
            raise ResearchError("RESEARCH_FACT_SNAPSHOT_TOO_LARGE")
        return snapshot

    @staticmethod
    def _evidence(signal: Signal) -> ResearchEvidence:
        if (
            signal.evidence_visibility == EvidenceVisibility.PRIVATE_SANITIZED.value
            and signal.public_provenance is not None
        ):
            raise ResearchError("RESEARCH_PRIVATE_PROVENANCE_INVALID")
        provenance = None
        raw = signal.public_provenance or {}
        if signal.evidence_visibility == EvidenceVisibility.PUBLIC.value:
            if signal.source_type == "trend_radar":
                provenance = TrendRadarProvenance(
                    kind="trend_radar",
                    source_kind=str(raw.get("source_kind") or "unknown"),
                    source_name=_optional_string(raw.get("source_name")),
                    url=_optional_string(raw.get("url")),
                )
            elif signal.source_type == "telegram":
                provenance = TelegramPublicProvenance(
                    kind="telegram_public",
                    platform="telegram",
                    chat_title=_optional_string(raw.get("chat_title")),
                    chat_username=_optional_string(raw.get("chat_username")),
                    url=_optional_string(raw.get("url")),
                )
            elif signal.source_type == "research":
                provenance = ResearchProvenance(
                    kind="research",
                    source_kind=str(raw.get("source_kind")),
                    canonical_url=str(raw.get("canonical_url")),
                )
        return ResearchEvidence(
            signal_id=signal.id,
            published_at=signal.published_at,
            sanitized_text=signal.normalized_text,
            evidence_visibility=signal.evidence_visibility,
            public_safe_provenance=provenance,
        )

    async def create_or_reuse(
        self,
        spec: ResearchRequestSpec,
        *,
        max_attempts: int,
    ) -> tuple[ResearchRequest, ResearchRequestPayload, bool]:
        request_id = uuid4()
        snapshot = await self.fact_snapshot(set(spec.source_event_ids))
        source_event_ids = (
            spec.source_event_ids
            if spec.trigger == ResearchTrigger.ASK_MISSING_FACT
            else sorted(spec.source_event_ids)
        )
        payload = ResearchRequestPayload(
            request_id=request_id,
            trigger=spec.trigger,
            source_event_ids=source_event_ids,
            research_questions=spec.research_questions,
            missing_fact_descriptions=spec.missing_fact_descriptions,
            current_fact_snapshot=snapshot,
            allowed_source_kinds=sorted(spec.allowed_source_kinds, key=lambda item: item.value),
        )
        input_hash = request_input_hash(payload)
        statement = (
            insert(ResearchRequest)
            .values(
                id=request_id,
                idempotency_key=spec.idempotency_key,
                trigger=spec.trigger.value,
                status=ResearchStatus.PENDING.value,
                input_hash=input_hash,
                request_payload=payload.model_dump(mode="json"),
                max_attempts=max_attempts,
            )
            .on_conflict_do_nothing(index_elements=[ResearchRequest.idempotency_key])
            .returning(ResearchRequest)
        )
        request = (await self.database.execute(statement)).scalar_one_or_none()
        inserted = request is not None
        if request is None:
            request = (
                await self.database.execute(
                    select(ResearchRequest).where(
                        ResearchRequest.idempotency_key == spec.idempotency_key
                    )
                )
            ).scalar_one()
            existing = ResearchRequestPayload.model_validate(request.request_payload)
            candidate = payload.model_copy(update={"request_id": request.id})
            if request.input_hash != request_input_hash(candidate):
                await self.database.rollback()
                raise ResearchError("RESEARCH_IDEMPOTENCY_CONFLICT")
            payload = existing
        else:
            for event_id in payload.source_event_ids:
                self.database.add(
                    ResearchRequestEvent(research_request_id=request.id, event_id=event_id)
                )
        await self.database.commit()
        return request, payload, inserted

    async def start_run(self, request_id: UUID) -> tuple[ResearchRequest, ResearchRun]:
        request = (
            await self.database.execute(
                select(ResearchRequest)
                .where(ResearchRequest.id == request_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise ResearchError("RESEARCH_REQUEST_NOT_FOUND")
        if request.status not in {
            ResearchStatus.PENDING.value,
            ResearchStatus.PARTIAL.value,
            ResearchStatus.FAILED.value,
        }:
            raise ResearchError("RESEARCH_REQUEST_NOT_RETRYABLE")
        if request.attempt_count >= request.max_attempts:
            raise ResearchError("RESEARCH_ATTEMPTS_EXHAUSTED")
        request.attempt_count += 1
        request.status = ResearchStatus.RUNNING.value
        request.error_code = None
        request.started_at = datetime.now(UTC)
        request.finished_at = None
        run = ResearchRun(
            research_request_id=request.id,
            attempt=request.attempt_count,
            status=ResearchStatus.RUNNING.value,
            started_at=request.started_at,
        )
        self.database.add(run)
        await self.database.commit()
        return request, run

    async def artifact(self, request_id: UUID) -> ResearchDiscoveryArtifact | None:
        return (
            await self.database.execute(
                select(ResearchDiscoveryArtifact).where(
                    ResearchDiscoveryArtifact.research_request_id == request_id
                )
            )
        ).scalar_one_or_none()

    async def persist_discovery(
        self,
        *,
        request: ResearchRequest,
        run: ResearchRun,
        response: ResearchDiscoveryResponse,
        candidates: list[ResearchCandidateAudit],
    ) -> ResearchDiscoveryArtifact:
        artifact = ResearchDiscoveryArtifact(
            research_request_id=request.id,
            created_by_run_id=run.id,
            schema_version="research_discovery_audit.v1",
            input_hash=request.input_hash,
            payload=ResearchDiscoveryAudit(
                request_id=request.id,
                candidate_count=len(candidates),
                candidates=[
                    ResearchDiscoveryAuditCandidate(
                        candidate_index=candidate.candidate_index,
                        source_kind=candidate.source_kind,
                        candidate_url_hash=candidate.candidate_url_hash,
                        decision=(
                            "accepted"
                            if candidate.status is ResearchSourceStatus.PENDING
                            else "rejected"
                        ),
                        canonical_url=candidate.canonical_url,
                        relevance_summary=(
                            response.payload.candidates[
                                candidate.candidate_index
                            ].relevance_summary
                            if candidate.status is ResearchSourceStatus.PENDING
                            else None
                        ),
                        error_code=candidate.error_code,
                    )
                    for candidate in candidates
                ],
            ).model_dump(mode="json"),
            runtime="openclaw",
            provider=response.provider,
            model=response.model,
            token_usage=response.usage.model_dump(mode="json"),
        )
        self.database.add(artifact)
        for candidate in candidates:
            self.database.add(
                ResearchSource(
                    research_request_id=request.id,
                    candidate_index=candidate.candidate_index,
                    source_kind=candidate.source_kind.value,
                    candidate_url_hash=candidate.candidate_url_hash,
                    canonical_url=candidate.canonical_url,
                    canonical_url_hash=candidate.canonical_url_hash,
                    status=candidate.status.value,
                    error_code=candidate.error_code,
                )
            )
        await self.database.commit()
        return artifact

    async def sources(self, request_id: UUID) -> list[ResearchSource]:
        return list(
            (
                await self.database.execute(
                    select(ResearchSource)
                    .where(ResearchSource.research_request_id == request_id)
                    .order_by(ResearchSource.candidate_index)
                )
            ).scalars()
        )

    async def source_started(self, source: ResearchSource) -> None:
        source.attempt_count += 1
        source.status = ResearchSourceStatus.PENDING.value
        source.error_code = None
        await self.database.commit()

    async def source_succeeded(self, source: ResearchSource, raw_id: UUID) -> None:
        source.status = ResearchSourceStatus.SUCCEEDED.value
        source.raw_information_id = raw_id
        source.error_code = None
        await self.database.commit()

    async def source_failed(self, source: ResearchSource, error_code: str) -> None:
        source.status = ResearchSourceStatus.FAILED.value
        source.error_code = error_code
        await self.database.commit()

    async def finish(
        self,
        request: ResearchRequest,
        run: ResearchRun,
        *,
        status: ResearchStatus,
        error_code: str | None,
    ) -> None:
        finished = datetime.now(UTC)
        request.status = status.value
        request.error_code = error_code
        request.finished_at = finished
        run.status = status.value
        run.error_code = error_code
        run.finished_at = finished
        await self.database.commit()


class ResearchRunner:
    def __init__(
        self,
        *,
        repository: ResearchRepository,
        acquisition: AcquisitionRepository,
        client: ResearchDiscoveryClient,
        fetcher: ResearchFetcher,
        max_attempts: int,
        url_validator: URLValidator = validate_public_url,
        health_checker: ResearchHealthChecker | None = None,
    ) -> None:
        self.repository = repository
        self.acquisition = acquisition
        self.client = client
        self.fetcher = fetcher
        self.max_attempts = max_attempts
        self.url_validator = url_validator
        self.health_checker = health_checker

    async def create_and_run(self, spec: ResearchRequestSpec) -> ResearchRequest:
        request, payload, _inserted = await self.repository.create_or_reuse(
            spec,
            max_attempts=self.max_attempts,
        )
        if request.status == ResearchStatus.SUCCEEDED.value:
            return request
        return await self.run(request.id, payload=payload)

    async def run(
        self,
        request_id: UUID,
        *,
        payload: ResearchRequestPayload | None = None,
    ) -> ResearchRequest:
        request, run = await self.repository.start_run(request_id)
        if payload is None:
            payload = ResearchRequestPayload.model_validate(request.request_payload)
        try:
            artifact = await self.repository.artifact(request.id)
            if artifact is None:
                if self.health_checker is not None:
                    await self.health_checker.check()
                with TemporaryDirectory(prefix="infoscope-research-") as workdir:
                    response = await self.client.discover(payload, workdir=Path(workdir))
                candidates = await self._audit_candidates(response.payload)
                artifact = await self.repository.persist_discovery(
                    request=request,
                    run=run,
                    response=response,
                    candidates=candidates,
                )
            try:
                discovery_audit = ResearchDiscoveryAudit.model_validate(artifact.payload)
            except ValueError as error:
                raise ResearchError("RESEARCH_DISCOVERY_SCHEMA_INVALID") from error
            sources = await self.repository.sources(request.id)
            if (
                discovery_audit.request_id != request.id
                or len(sources) != discovery_audit.candidate_count
            ):
                raise ResearchError("RESEARCH_SOURCE_AUDIT_INCOMPLETE")
            if discovery_audit.candidate_count == 0:
                await self.repository.finish(
                    request, run, status=ResearchStatus.SUCCEEDED, error_code=None
                )
                return request
            if not sources or not any(source.canonical_url is not None for source in sources):
                await self.repository.finish(
                    request,
                    run,
                    status=ResearchStatus.FAILED,
                    error_code="RESEARCH_NO_VALID_CANDIDATES",
                )
                return request
            for source in sources:
                if (
                    source.status == ResearchSourceStatus.SUCCEEDED.value
                    or source.canonical_url is None
                ):
                    continue
                await self.repository.source_started(source)
                try:
                    source_kind = ResearchSourceKind(source.source_kind)
                    validated = await self.url_validator(source.canonical_url, source_kind)
                    fetched = await self.fetcher.fetch(source_kind, validated)
                    raw = await self._persist_raw(request, source, fetched)
                    await self.repository.source_succeeded(source, raw.id)
                except (ResearchURLRejected, ResearchFetchError) as error:
                    await self.repository.source_failed(source, error.error_code)
            sources = await self.repository.sources(request.id)
            succeeded = sum(
                item.status == ResearchSourceStatus.SUCCEEDED.value for item in sources
            )
            if succeeded == 0:
                status = ResearchStatus.FAILED
                error_code = "RESEARCH_ALL_SOURCES_FAILED"
            elif succeeded < len(sources):
                status = ResearchStatus.PARTIAL
                error_code = "RESEARCH_PARTIAL_SOURCE_FAILURE"
            else:
                status = ResearchStatus.SUCCEEDED
                error_code = None
            await self.repository.finish(request, run, status=status, error_code=error_code)
            return request
        except (ResearchRuntimeError, ResearchError) as error:
            await self.repository.finish(
                request,
                run,
                status=ResearchStatus.FAILED,
                error_code=error.error_code,
            )
            raise

    async def _audit_candidates(
        self, discovery: ResearchDiscovery
    ) -> list[ResearchCandidateAudit]:
        audits: list[ResearchCandidateAudit] = []
        seen: set[str] = set()
        for index, candidate in enumerate(discovery.candidates):
            candidate_url_hash = sha256(candidate.source_url.encode("utf-8")).hexdigest()
            try:
                validated = await self.url_validator(
                    candidate.source_url, candidate.source_kind
                )
            except ResearchURLRejected as error:
                audits.append(
                    ResearchCandidateAudit(
                        candidate_index=index,
                        source_kind=candidate.source_kind,
                        candidate_url_hash=candidate_url_hash,
                        status=ResearchSourceStatus.FAILED,
                        error_code=error.error_code,
                    )
                )
                continue
            if validated.canonical_url_hash in seen:
                audits.append(
                    ResearchCandidateAudit(
                        candidate_index=index,
                        source_kind=candidate.source_kind,
                        candidate_url_hash=candidate_url_hash,
                        status=ResearchSourceStatus.FAILED,
                        error_code="RESEARCH_DUPLICATE_CANDIDATE",
                    )
                )
                continue
            seen.add(validated.canonical_url_hash)
            audits.append(
                ResearchCandidateAudit(
                    candidate_index=index,
                    source_kind=candidate.source_kind,
                    candidate_url_hash=candidate_url_hash,
                    status=ResearchSourceStatus.PENDING,
                    canonical_url=validated.canonical_url,
                    canonical_url_hash=validated.canonical_url_hash,
                )
            )
        return audits

    async def _persist_raw(
        self,
        request: ResearchRequest,
        source: ResearchSource,
        fetched: FetchedResearchSource,
    ):
        content_hash = sha256(fetched.normalized_text.encode("utf-8")).hexdigest()
        source_key_hash = sha256(
            f"{fetched.source_kind.value}\n{fetched.canonical_url}\n{content_hash}".encode()
        ).hexdigest()
        return (
            await self.acquisition.persist_raw(
                RawInformationInput(
                    source_type="research",
                    source_key=f"research:v1:{source_key_hash}",
                    source_visibility=SourceVisibility.PUBLIC,
                    acquired_at=datetime.now(UTC),
                    published_at=fetched.published_at,
                    content_text=fetched.normalized_text,
                    payload={"title": fetched.title},
                    provenance={
                        "source_kind": fetched.source_kind.value,
                        "canonical_url": fetched.canonical_url,
                    },
                    collector_metadata={
                        "research_request_id": str(request.id),
                        "research_source_id": str(source.id),
                        "fetcher_name": fetched.fetcher_name,
                        "fetcher_version": fetched.fetcher_version,
                        **(
                            {
                                "parser": "beautifulsoup4",
                                "parser_version": "4.15.0",
                            }
                            if fetched.fetcher_name == "direct_https_html"
                            else {}
                        ),
                    },
                    content_hash=content_hash,
                )
            )
        ).raw


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
