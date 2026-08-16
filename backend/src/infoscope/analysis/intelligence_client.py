from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from infoscope.analysis.ask_finalization_prompt import (
    ASK_FINALIZATION_SYSTEM_PROMPT,
    build_ask_finalization_prompt,
)
from infoscope.analysis.ask_prompt import ASK_COMPARISON_SYSTEM_PROMPT, build_ask_comparison_prompt
from infoscope.analysis.ask_reconciliation_prompt import (
    ASK_EVENT_RECONCILIATION_SYSTEM_PROMPT,
    build_ask_event_reconciliation_prompt,
)
from infoscope.analysis.ask_schemas import (
    AskComparisonInput,
    AskComparisonPayload,
    AskComparisonResponse,
    AskEventReconciliationInput,
    AskEventReconciliationPayload,
    AskEventReconciliationResponse,
    AskFinalizationInput,
    AskFinalizationModelPayload,
    AskFinalizationResponse,
)
from infoscope.analysis.backwrite_prompt import (
    BACKWRITE_RECONCILIATION_SYSTEM_PROMPT,
    build_backwrite_reconciliation_prompt,
)
from infoscope.analysis.backwrite_schemas import (
    BackwriteReconciliationInput,
    BackwriteReconciliationPayload,
    BackwriteReconciliationResponse,
)
from infoscope.analysis.brief_prompt import BRIEF_SYSTEM_PROMPT, build_brief_prompt
from infoscope.analysis.brief_schemas import (
    MAX_INPUT_BYTES as BRIEF_MAX_INPUT_BYTES,
)
from infoscope.analysis.brief_schemas import (
    MAX_OUTPUT_BYTES as BRIEF_MAX_OUTPUT_BYTES,
)
from infoscope.analysis.brief_schemas import (
    BriefInput,
    BriefPayload,
    BriefResponse,
)
from infoscope.analysis.brief_schemas import (
    canonical_bytes as brief_canonical_bytes,
)
from infoscope.analysis.client import AnalysisError
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.intelligence_prompt import (
    BASE_ANALYSIS_SYSTEM_PROMPT,
    CLAIM_SYSTEM_PROMPT,
    CONFLICT_SYSTEM_PROMPT,
    TIMELINE_SYSTEM_PROMPT,
    build_base_analysis_prompt,
    build_claim_prompt,
    build_conflict_prompt,
    build_timeline_prompt,
)
from infoscope.analysis.intelligence_schemas import (
    BaseAnalysisPayload,
    BaseAnalysisResponse,
    ClaimExtractionPayload,
    ClaimExtractionResponse,
    ConflictAnalysisPayload,
    ConflictAnalysisResponse,
    EventBaseAnalysisInput,
    EventClaimInput,
    EventConflictInput,
    EventTimelineInput,
    ExistingBaseAnalysisCandidate,
    ExistingClaimCandidate,
    ExistingConflictCandidate,
    ExistingTimelineCandidate,
    TimelineReconstructionPayload,
    TimelineReconstructionResponse,
)
from infoscope.analysis.personalization_prompt import (
    PERSONALIZATION_SYSTEM_PROMPT,
    build_personalization_prompt,
)
from infoscope.analysis.personalization_schemas import (
    MAX_CANONICAL_BYTES,
    PersonalizationInput,
    PersonalizationPayload,
    PersonalizationResponse,
    canonical_bytes,
)
from infoscope.analysis.schemas import TokenUsage

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class DeepSeekIntelligenceClient:
    def __init__(self, *, client: httpx.AsyncClient, config: AnalysisConfig) -> None:
        self.client = client
        self.config = config
        self._key_index = 0
        self._key_lock = asyncio.Lock()

    async def extract_claims(
        self, *, events: list[EventClaimInput], candidates: list[ExistingClaimCandidate]
    ) -> ClaimExtractionResponse:
        payload, model, usage = await self._request(
            system=CLAIM_SYSTEM_PROMPT,
            user=build_claim_prompt(events, candidates),
            payload_type=ClaimExtractionPayload,
        )
        return ClaimExtractionResponse(
            payload=payload, provider="deepseek", model=model, token_usage=usage
        )

    async def reconstruct_timeline(
        self, *, events: list[EventTimelineInput], candidates: list[ExistingTimelineCandidate]
    ) -> TimelineReconstructionResponse:
        payload, model, usage = await self._request(
            system=TIMELINE_SYSTEM_PROMPT,
            user=build_timeline_prompt(events, candidates),
            payload_type=TimelineReconstructionPayload,
        )
        return TimelineReconstructionResponse(
            payload=payload, provider="deepseek", model=model, token_usage=usage
        )

    async def analyze_conflicts(
        self, *, events: list[EventConflictInput], candidates: list[ExistingConflictCandidate]
    ) -> ConflictAnalysisResponse:
        payload, model, usage = await self._request(
            system=CONFLICT_SYSTEM_PROMPT,
            user=build_conflict_prompt(events, candidates),
            payload_type=ConflictAnalysisPayload,
        )
        return ConflictAnalysisResponse(
            payload=payload, provider="deepseek", model=model, token_usage=usage
        )

    async def analyze_base(
        self,
        *,
        events: list[EventBaseAnalysisInput],
        candidates: list[ExistingBaseAnalysisCandidate],
    ) -> BaseAnalysisResponse:
        payload, model, usage = await self._request(
            system=BASE_ANALYSIS_SYSTEM_PROMPT,
            user=build_base_analysis_prompt(events, candidates),
            payload_type=BaseAnalysisPayload,
        )
        return BaseAnalysisResponse(
            payload=payload, provider="deepseek", model=model, token_usage=usage
        )

    async def compare_ask(self, value: AskComparisonInput) -> AskComparisonResponse:
        payload, model, usage = await self._request(
            system=ASK_COMPARISON_SYSTEM_PROMPT,
            user=build_ask_comparison_prompt(value),
            payload_type=AskComparisonPayload,
        )
        return AskComparisonResponse(
            payload=payload,
            provider="deepseek",
            model=model,
            token_usage=usage,
        )

    async def reconcile_ask_events(
        self, value: AskEventReconciliationInput
    ) -> AskEventReconciliationResponse:
        payload, model, usage = await self._request(
            system=ASK_EVENT_RECONCILIATION_SYSTEM_PROMPT,
            user=build_ask_event_reconciliation_prompt(value),
            payload_type=AskEventReconciliationPayload,
        )
        return AskEventReconciliationResponse(
            payload=payload,
            provider="deepseek",
            model=model,
            token_usage=usage,
        )

    async def finalize_ask(self, value: AskFinalizationInput) -> AskFinalizationResponse:
        payload, model, usage = await self._request(
            system=ASK_FINALIZATION_SYSTEM_PROMPT,
            user=build_ask_finalization_prompt(value),
            payload_type=AskFinalizationModelPayload,
        )
        return AskFinalizationResponse(
            payload=payload,
            provider="deepseek",
            model=model,
            token_usage=usage,
        )

    async def reconcile_backwrite_event(
        self, value: BackwriteReconciliationInput
    ) -> BackwriteReconciliationResponse:
        payload, model, usage = await self._request(
            system=BACKWRITE_RECONCILIATION_SYSTEM_PROMPT,
            user=build_backwrite_reconciliation_prompt(value),
            payload_type=BackwriteReconciliationPayload,
        )
        return BackwriteReconciliationResponse(
            payload=payload,
            provider="deepseek",
            model=model,
            token_usage=usage,
        )

    async def personalize(self, value: PersonalizationInput) -> PersonalizationResponse:
        if len(canonical_bytes(value)) > MAX_CANONICAL_BYTES:
            raise AnalysisError("PERSONALIZATION_INPUT_LIMIT_EXCEEDED")
        payload, model, usage = await self._request(
            system=PERSONALIZATION_SYSTEM_PROMPT,
            user=build_personalization_prompt(value),
            payload_type=PersonalizationPayload,
            output_limit=MAX_CANONICAL_BYTES,
            schema_error="PERSONALIZATION_SCHEMA_INVALID",
            output_error="PERSONALIZATION_OUTPUT_LIMIT_EXCEEDED",
        )
        return PersonalizationResponse(
            payload=payload,
            provider="deepseek",
            model=model,
            token_usage=usage,
        )

    async def generate_brief(self, value: BriefInput) -> BriefResponse:
        if len(brief_canonical_bytes(value)) > BRIEF_MAX_INPUT_BYTES:
            raise AnalysisError("BRIEF_INPUT_LIMIT_EXCEEDED")
        payload, model, usage = await self._request(
            system=BRIEF_SYSTEM_PROMPT,
            user=build_brief_prompt(value),
            payload_type=BriefPayload,
            output_limit=BRIEF_MAX_OUTPUT_BYTES,
            schema_error="BRIEF_SCHEMA_INVALID",
            output_error="BRIEF_OUTPUT_LIMIT_EXCEEDED",
        )
        return BriefResponse(
            payload=payload,
            provider="deepseek",
            model=model,
            token_usage=usage,
        )

    async def _next_key(self) -> str:
        async with self._key_lock:
            key = self.config.api_keys[self._key_index % len(self.config.api_keys)]
            self._key_index += 1
            return key

    async def _request(
        self,
        *,
        system: str,
        user: str,
        payload_type: type[PayloadT],
        output_limit: int | None = None,
        schema_error: str = "ANALYSIS_SCHEMA_INVALID",
        output_error: str = "ANALYSIS_SCHEMA_INVALID",
    ) -> tuple[PayloadT, str, TokenUsage]:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = await self.client.post(
                    f"{self.config.api_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {await self._next_key()}"},
                    json={
                        "model": self.config.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {"type": "json_object"},
                        "thinking": {"type": "enabled"},
                        "max_tokens": self.config.max_tokens,
                        "temperature": 0,
                    },
                    timeout=self.config.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.config.max_retries:
                        await asyncio.sleep(min(2**attempt, 8))
                        continue
                    raise AnalysisError(
                        "ANALYSIS_RATE_LIMITED"
                        if response.status_code == 429
                        else "ANALYSIS_UPSTREAM_UNAVAILABLE"
                    )
                if not response.is_success:
                    raise AnalysisError("ANALYSIS_REQUEST_REJECTED")
                return self._parse(
                    response.json(),
                    payload_type,
                    output_limit=output_limit,
                    schema_error=schema_error,
                    output_error=output_error,
                )
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                if attempt >= self.config.max_retries:
                    raise AnalysisError("ANALYSIS_REQUEST_FAILED") from error
                await asyncio.sleep(min(2**attempt, 8))
            except AnalysisError as error:
                if attempt >= self.config.max_retries or error.error_code not in {
                    "ANALYSIS_EMPTY_RESPONSE",
                    "ANALYSIS_INVALID_JSON",
                    "ANALYSIS_SCHEMA_INVALID",
                    "ANALYSIS_TRUNCATED",
                    "PERSONALIZATION_SCHEMA_INVALID",
                    "PERSONALIZATION_OUTPUT_LIMIT_EXCEEDED",
                    "BRIEF_SCHEMA_INVALID",
                    "BRIEF_OUTPUT_LIMIT_EXCEEDED",
                }:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
        raise AnalysisError("ANALYSIS_REQUEST_FAILED")

    def _parse(
        self,
        document: dict[str, Any],
        payload_type: type[PayloadT],
        *,
        output_limit: int | None = None,
        schema_error: str = "ANALYSIS_SCHEMA_INVALID",
        output_error: str = "ANALYSIS_SCHEMA_INVALID",
    ) -> tuple[PayloadT, str, TokenUsage]:
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AnalysisError("ANALYSIS_EMPTY_RESPONSE")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise AnalysisError("ANALYSIS_TRUNCATED")
        content = choice.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise AnalysisError("ANALYSIS_EMPTY_RESPONSE")
        if output_limit is not None and len(content.encode("utf-8")) > output_limit:
            raise AnalysisError(output_error)
        try:
            payload = payload_type.model_validate(json.loads(content))
            usage_document = document.get("usage") or {}
            usage = TokenUsage.model_validate(
                {
                    key: usage_document.get(key, 0)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            )
        except json.JSONDecodeError as error:
            raise AnalysisError("ANALYSIS_INVALID_JSON") from error
        except ValidationError as error:
            raise AnalysisError(schema_error) from error
        return payload, str(document.get("model") or self.config.model), usage
