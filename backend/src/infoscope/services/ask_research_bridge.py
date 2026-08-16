from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.analysis.ask_schemas import (
    AskComparisonInput,
    AskComparisonPayload,
    AskResearchArtifactPayload,
    AskResearchResult,
)
from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.integrations.research.schemas import ResearchRequestPayload, ResearchRequestSpec
from infoscope.models import (
    AskComparisonArtifact,
    AskRequest,
    AskResearchArtifact,
    AskResearchBridge,
    NormalizationStatus,
    RawInformation,
    ResearchRequest,
    ResearchSource,
    ResearchSourceKind,
    ResearchSourceStatus,
    ResearchStatus,
    ResearchTrigger,
)
from infoscope.services.acquisition import AcquisitionRepository
from infoscope.services.normalization import DeterministicNormalizer, NormalizationError
from infoscope.services.research import ResearchError, ResearchRepository, ResearchRunner

ASK_RESEARCH_IDEMPOTENCY_NAMESPACE = UUID("a9f9c7ea-115c-4a44-a4c6-72768af17f2c")
TERMINAL_RESEARCH_ERRORS = {
    "RESEARCH_ATTEMPTS_EXHAUSTED",
    "RESEARCH_FACT_SNAPSHOT_INVALID",
    "RESEARCH_FACT_SNAPSHOT_TOO_LARGE",
    "RESEARCH_IDEMPOTENCY_CONFLICT",
    "RESEARCH_NO_VALID_CANDIDATES",
    "RESEARCH_PRIVATE_PROVENANCE_INVALID",
}


class AskResearchBridgeError(RuntimeError):
    def __init__(self, error_code: str, *, retryable: bool) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class PreparedBridge:
    request: AskRequest
    bridge: AskResearchBridge
    comparison_artifact: AskComparisonArtifact
    comparison_input: AskComparisonInput
    comparison_output: AskComparisonPayload
    should_run: bool


class AskResearchBridgeRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def prepare(self, ask_id: UUID, *, max_attempts: int) -> PreparedBridge:
        request = (
            await self.database.execute(
                select(AskRequest).where(AskRequest.id == ask_id).with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise AskResearchBridgeError("ASK_REQUEST_NOT_FOUND", retryable=False)
        artifact = (
            await self.database.execute(
                select(AskComparisonArtifact).where(
                    AskComparisonArtifact.ask_request_id == request.id
                )
            )
        ).scalar_one_or_none()
        if artifact is None:
            raise AskResearchBridgeError(
                "ASK_COMPARISON_ARTIFACT_MISSING", retryable=False
            )
        try:
            comparison_input = AskComparisonInput.model_validate(artifact.input_snapshot)
            comparison_output = AskComparisonPayload.model_validate(artifact.output)
        except ValueError as error:
            raise AskResearchBridgeError(
                "ASK_COMPARISON_ARTIFACT_INVALID", retryable=False
            ) from error
        if (
            comparison_input.ask_id != request.id
            or comparison_output.ask_id != request.id
            or comparison_output.decision != "research_required"
        ):
            raise AskResearchBridgeError(
                "ASK_RESEARCH_NOT_REQUIRED", retryable=False
            )
        bridge = (
            await self.database.execute(
                select(AskResearchBridge).where(
                    AskResearchBridge.ask_request_id == request.id
                )
            )
        ).scalar_one_or_none()
        if bridge is not None and bridge.status in {"running", "completed"}:
            await self.database.commit()
            return PreparedBridge(
                request,
                bridge,
                artifact,
                comparison_input,
                comparison_output,
                False,
            )
        if request.status != "pending" or request.stage != "awaiting_research":
            raise AskResearchBridgeError(
                "ASK_RESEARCH_BRIDGE_NOT_RETRYABLE", retryable=False
            )
        started = datetime.now(UTC)
        if bridge is None:
            bridge = AskResearchBridge(
                ask_request_id=request.id,
                comparison_artifact_id=artifact.id,
                idempotency_key=uuid5(
                    ASK_RESEARCH_IDEMPOTENCY_NAMESPACE,
                    f"{request.id}:{artifact.id}:ask_research_bridge.v1",
                ),
                status="running",
                attempt_count=1,
                max_attempts=max_attempts,
                started_at=started,
            )
            self.database.add(bridge)
        else:
            if bridge.attempt_count >= bridge.max_attempts:
                request.status = "failed"
                request.error_code = "ASK_RESEARCH_BRIDGE_ATTEMPTS_EXHAUSTED"
                request.finished_at = started
                bridge.error_code = "ASK_RESEARCH_BRIDGE_ATTEMPTS_EXHAUSTED"
                bridge.finished_at = started
                await self.database.commit()
                raise AskResearchBridgeError(
                    "ASK_RESEARCH_BRIDGE_ATTEMPTS_EXHAUSTED", retryable=False
                )
            bridge.status = "running"
            bridge.attempt_count += 1
            bridge.error_code = None
            bridge.started_at = started
            bridge.finished_at = None
        request.status = "running"
        request.stage = "awaiting_research"
        request.error_code = None
        request.finished_at = None
        await self.database.commit()
        return PreparedBridge(
            request,
            bridge,
            artifact,
            comparison_input,
            comparison_output,
            True,
        )

    async def attach_research_request(
        self, bridge_id: UUID, research_request_id: UUID
    ) -> None:
        bridge = await self.database.get(AskResearchBridge, bridge_id)
        if bridge is None:
            raise AskResearchBridgeError("ASK_RESEARCH_BRIDGE_MISSING", retryable=False)
        if bridge.research_request_id not in {None, research_request_id}:
            raise AskResearchBridgeError(
                "ASK_RESEARCH_REQUEST_MISMATCH", retryable=False
            )
        bridge.research_request_id = research_request_id
        await self.database.commit()

    async def linked_research_request(
        self, bridge: AskResearchBridge
    ) -> ResearchRequest | None:
        if bridge.research_request_id is not None:
            request = await self.database.get(
                ResearchRequest, bridge.research_request_id
            )
        else:
            request = (
                await self.database.execute(
                    select(ResearchRequest).where(
                        ResearchRequest.idempotency_key == bridge.idempotency_key
                    )
                )
            ).scalar_one_or_none()
        if request is not None and request.idempotency_key != bridge.idempotency_key:
            raise AskResearchBridgeError(
                "ASK_RESEARCH_REQUEST_MISMATCH", retryable=False
            )
        return request

    async def successful_sources(self, research_request_id: UUID) -> list[ResearchSource]:
        return list(
            (
                await self.database.execute(
                    select(ResearchSource)
                    .where(
                        ResearchSource.research_request_id == research_request_id,
                        ResearchSource.status == ResearchSourceStatus.SUCCEEDED.value,
                        ResearchSource.raw_information_id.is_not(None),
                    )
                    .order_by(ResearchSource.candidate_index)
                )
            ).scalars()
        )

    async def persist_success(
        self,
        prepared: PreparedBridge,
        payload: AskResearchArtifactPayload,
    ) -> AskRequest:
        request = (
            await self.database.execute(
                select(AskRequest)
                .where(AskRequest.id == prepared.request.id)
                .with_for_update()
            )
        ).scalar_one()
        bridge = (
            await self.database.execute(
                select(AskResearchBridge)
                .where(AskResearchBridge.id == prepared.bridge.id)
                .with_for_update()
            )
        ).scalar_one()
        existing = (
            await self.database.execute(
                select(AskResearchArtifact).where(
                    AskResearchArtifact.bridge_id == bridge.id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            self.database.add(
                AskResearchArtifact(
                    bridge_id=bridge.id,
                    ask_request_id=request.id,
                    comparison_artifact_id=prepared.comparison_artifact.id,
                    research_request_id=payload.research_request_id,
                    schema_version="ask_research_bridge.v1",
                    payload=payload.model_dump(mode="json"),
                )
            )
        finished = datetime.now(UTC)
        bridge.status = "completed"
        bridge.error_code = None
        bridge.finished_at = finished
        request.status = "pending"
        request.stage = "awaiting_reconciliation"
        request.error_code = None
        request.finished_at = None
        await self.database.commit()
        return request

    async def persist_failure(
        self,
        prepared: PreparedBridge,
        *,
        error_code: str,
        retryable: bool,
    ) -> AskRequest:
        await self.database.rollback()
        request = await self.database.get(AskRequest, prepared.request.id)
        bridge = await self.database.get(AskResearchBridge, prepared.bridge.id)
        if request is None or bridge is None:
            raise AskResearchBridgeError("ASK_RESEARCH_BRIDGE_MISSING", retryable=False)
        terminal = not retryable or bridge.attempt_count >= bridge.max_attempts
        if bridge.attempt_count >= bridge.max_attempts and retryable:
            error_code = "ASK_RESEARCH_BRIDGE_ATTEMPTS_EXHAUSTED"
        finished = datetime.now(UTC)
        bridge.status = "failed"
        bridge.error_code = error_code
        bridge.finished_at = finished
        request.status = "failed" if terminal else "pending"
        request.stage = "awaiting_research"
        request.error_code = error_code if terminal else None
        request.finished_at = finished if terminal else None
        await self.database.commit()
        return request


class AskResearchBridgeRunner:
    def __init__(
        self,
        *,
        repository: AskResearchBridgeRepository,
        research_repository: ResearchRepository,
        research_runner: ResearchRunner,
        acquisition: AcquisitionRepository,
        max_attempts: int,
        research_max_attempts: int,
        normalizer: DeterministicNormalizer | None = None,
    ) -> None:
        self.repository = repository
        self.research_repository = research_repository
        self.research_runner = research_runner
        self.acquisition = acquisition
        self.max_attempts = max_attempts
        self.research_max_attempts = research_max_attempts
        self.normalizer = normalizer or DeterministicNormalizer()

    async def run(self, ask_id: UUID) -> AskRequest:
        prepared = await self.repository.prepare(ask_id, max_attempts=self.max_attempts)
        if not prepared.should_run:
            return prepared.request
        research: ResearchRequest | None = None
        try:
            spec, source_event_ids = self._research_spec(prepared)
            research = await self.repository.linked_research_request(prepared.bridge)
            if research is None:
                research, payload, _inserted = (
                    await self.research_repository.create_or_reuse(
                        spec,
                        max_attempts=self.research_max_attempts,
                    )
                )
            else:
                try:
                    payload = ResearchRequestPayload.model_validate(
                        research.request_payload
                    )
                except ValueError as error:
                    raise AskResearchBridgeError(
                        "ASK_RESEARCH_REQUEST_INVALID", retryable=False
                    ) from error
                self._validate_linked_research(prepared, spec, research, payload)
            await self.repository.attach_research_request(prepared.bridge.id, research.id)
            if research.status == ResearchStatus.FAILED.value and (
                research.error_code in TERMINAL_RESEARCH_ERRORS
                or research.attempt_count >= research.max_attempts
            ):
                raise AskResearchBridgeError(
                    "ASK_RESEARCH_NO_USABLE_SIGNALS",
                    retryable=False,
                )
            if research.status in {
                ResearchStatus.PENDING.value,
                ResearchStatus.FAILED.value,
            }:
                research = await self.research_runner.run(research.id, payload=payload)
            elif research.status == ResearchStatus.RUNNING.value:
                raise AskResearchBridgeError(
                    "ASK_RESEARCH_REQUEST_RUNNING", retryable=True
                )
            results, normalization_failures = (
                await self._normalize_successful_sources(research.id)
            )
            if not results:
                retryable = normalization_failures > 0 or self._research_is_retryable(
                    research
                )
                raise AskResearchBridgeError(
                    (
                        "ASK_RESEARCH_NORMALIZATION_FAILED"
                        if normalization_failures > 0
                        else "ASK_RESEARCH_RETRYABLE_FAILURE"
                        if retryable
                        else "ASK_RESEARCH_NO_USABLE_SIGNALS"
                    ),
                    retryable=retryable,
                )
            research_status = (
                "partial"
                if research.status == ResearchStatus.PARTIAL.value
                else "succeeded"
            )
            artifact = AskResearchArtifactPayload(
                ask_id=prepared.request.id,
                comparison_artifact_id=prepared.comparison_artifact.id,
                research_request_id=research.id,
                source_event_ids=source_event_ids,
                research_status=research_status,
                results=results,
            )
            return await self.repository.persist_success(prepared, artifact)
        except (ResearchRuntimeError, ResearchError) as error:
            retryable = (
                error.error_code not in TERMINAL_RESEARCH_ERRORS
                and (
                    research is None
                    or research.attempt_count < research.max_attempts
                )
            )
            await self.repository.persist_failure(
                prepared,
                error_code=error.error_code,
                retryable=retryable,
            )
            raise
        except AskResearchBridgeError as error:
            await self.repository.persist_failure(
                prepared,
                error_code=error.error_code,
                retryable=error.retryable,
            )
            raise
        except SQLAlchemyError:
            await self.repository.persist_failure(
                prepared,
                error_code="ASK_RESEARCH_PERSISTENCE_FAILED",
                retryable=True,
            )
            raise

    @staticmethod
    def _research_spec(
        prepared: PreparedBridge,
    ) -> tuple[ResearchRequestSpec, list[UUID]]:
        missing_events = {
            event_id
            for missing in prepared.comparison_output.missing_facts
            for event_id in missing.event_ids
        }
        source_event_ids = [
            event_id
            for event_id in prepared.comparison_input.selected_event_ids
            if event_id in missing_events
        ]
        if not source_event_ids:
            raise AskResearchBridgeError(
                "ASK_RESEARCH_MISSING_FACTS_INVALID", retryable=False
            )
        return (
            ResearchRequestSpec(
                idempotency_key=prepared.bridge.idempotency_key,
                trigger=ResearchTrigger.ASK_MISSING_FACT,
                source_event_ids=source_event_ids,
                research_questions=[
                    item.question for item in prepared.comparison_output.missing_facts
                ],
                missing_fact_descriptions=[],
                allowed_source_kinds=[
                    ResearchSourceKind.WEB_PAGE,
                    ResearchSourceKind.GITHUB_DOCUMENT,
                ],
            ),
            source_event_ids,
        )

    async def _normalize_successful_sources(
        self, research_request_id: UUID
    ) -> tuple[list[AskResearchResult], int]:
        results: list[AskResearchResult] = []
        failures = 0
        for source in await self.repository.successful_sources(research_request_id):
            if source.raw_information_id is None:
                continue
            raw = await self.repository.database.get(
                RawInformation, source.raw_information_id
            )
            if raw is None or raw.source_type != "research":
                raise AskResearchBridgeError(
                    "ASK_RESEARCH_RAW_INVALID", retryable=False
                )
            if raw.normalization_status == NormalizationStatus.PROCESSING.value:
                raise AskResearchBridgeError(
                    "ASK_RESEARCH_NORMALIZATION_BUSY", retryable=True
                )
            if raw.normalization_status in {
                NormalizationStatus.PENDING.value,
                NormalizationStatus.FAILED.value,
            }:
                await self.acquisition.mark_normalization_started(raw)
                try:
                    normalized = self.normalizer.normalize(raw)
                except NormalizationError as error:
                    await self.acquisition.mark_normalization_failed(
                        raw, error_code=error.error_code
                    )
                    failures += 1
                    continue
                await self.acquisition.persist_signal(
                    raw=raw,
                    value=normalized,
                    normalized_at=datetime.now(UTC),
                )
            signals = await self.acquisition.list_signals_for_raw(raw.id)
            if not signals:
                raise AskResearchBridgeError(
                    "ASK_RESEARCH_SIGNAL_MISSING", retryable=False
                )
            results.append(
                AskResearchResult(
                    candidate_index=source.candidate_index,
                    research_source_id=source.id,
                    raw_information_id=raw.id,
                    signal_ids=[item.id for item in signals],
                )
            )
        return results, failures

    @staticmethod
    def _validate_linked_research(
        prepared: PreparedBridge,
        spec: ResearchRequestSpec,
        request: ResearchRequest,
        payload: ResearchRequestPayload,
    ) -> None:
        if (
            request.idempotency_key != prepared.bridge.idempotency_key
            or payload.request_id != request.id
            or payload.trigger != spec.trigger
            or payload.source_event_ids != spec.source_event_ids
            or payload.research_questions != spec.research_questions
            or payload.missing_fact_descriptions
            or set(payload.allowed_source_kinds) != set(spec.allowed_source_kinds)
        ):
            raise AskResearchBridgeError(
                "ASK_RESEARCH_REQUEST_MISMATCH", retryable=False
            )

    @staticmethod
    def _research_is_retryable(request: ResearchRequest) -> bool:
        return (
            request.status == ResearchStatus.FAILED.value
            and request.attempt_count < request.max_attempts
            and request.error_code not in TERMINAL_RESEARCH_ERRORS
        )
