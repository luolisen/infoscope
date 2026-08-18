from __future__ import annotations

import asyncio
import json
import logging
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
logger = logging.getLogger("infoscope.analysis.intelligence")


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
            payload=payload, provider=self.config.provider, model=model, token_usage=usage
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
            payload=payload, provider=self.config.provider, model=model, token_usage=usage
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
            payload=payload, provider=self.config.provider, model=model, token_usage=usage
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
            payload=payload, provider=self.config.provider, model=model, token_usage=usage
        )

    async def compare_ask(self, value: AskComparisonInput) -> AskComparisonResponse:
        payload, model, usage = await self._request(
            system=ASK_COMPARISON_SYSTEM_PROMPT,
            user=build_ask_comparison_prompt(value),
            payload_type=AskComparisonPayload,
        )
        return AskComparisonResponse(
            payload=payload,
            provider=self.config.provider,
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
            provider=self.config.provider,
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
            provider=self.config.provider,
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
            provider=self.config.provider,
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
            provider=self.config.provider,
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
            provider=self.config.provider,
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
        last_error = "ANALYSIS_REQUEST_FAILED"
        for attempt in range(self.config.max_retries + 1):
            try:
                user_prompt = user
                repair_instruction = self._repair_instruction(
                    last_error, payload_type=payload_type
                )
                if attempt > 0 and repair_instruction is not None:
                    user_prompt = f"{user}\n\n{repair_instruction}"
                request_payload: dict[str, Any] = {
                    "model": self.config.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                        {
                            "role": "user",
                            "content": "Return exactly one valid json object and no prose.",
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": self.config.max_tokens,
                    "temperature": 0,
                }
                if self.config.supports_deepseek_thinking:
                    request_payload["thinking"] = {"type": "disabled"}
                response = await self.client.post(
                    f"{self.config.api_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {await self._next_key()}"},
                    json=request_payload,
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
                last_error = "ANALYSIS_REQUEST_FAILED"
                if attempt >= self.config.max_retries:
                    raise AnalysisError("ANALYSIS_REQUEST_FAILED") from error
                await asyncio.sleep(min(2**attempt, 8))
            except AnalysisError as error:
                last_error = error.error_code
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

    @staticmethod
    def _repair_instruction(
        error_code: str, *, payload_type: type[BaseModel]
    ) -> str | None:
        if error_code == "ANALYSIS_TRUNCATED":
            return (
                "The previous response was truncated. Regenerate a materially more concise but "
                "complete replacement JSON object. Preserve every required Backend-supplied ID "
                "and decision, keep all text well below its limit, omit optional verbosity, and "
                "do not emit prose or code fences."
            )
        if error_code in {
            "ANALYSIS_SCHEMA_INVALID",
            "PERSONALIZATION_SCHEMA_INVALID",
            "BRIEF_SCHEMA_INVALID",
        }:
            if payload_type is BaseAnalysisPayload:
                return (
                    "The previous response violated the strict Base Analysis schema. Regenerate "
                    "from the original input. Every entities item must contain exactly name and "
                    "entity_type; never emit entity_id, id, aliases, or any extra field. Use only "
                    "Backend-supplied IDs, return exactly one decision for every input Event, and "
                    "return one complete replacement JSON object only."
                )
            if payload_type is PersonalizationPayload:
                return (
                    "The previous response violated the strict Personalization schema. "
                    "Regenerate from the original input with exactly one decision per input "
                    "Event in the original order. Every decision object must contain exactly "
                    "these keys: event_id, relevant, priority, why_it_matters, "
                    "personalized_angle, matched_scope_ids, matched_focus_ids, rationale. "
                    "Never add punctuation such as a trailing colon to a key, never invent an "
                    "alternate key, and never omit a required key; use null or an empty array "
                    "where the schema requires it. Return one complete replacement JSON object "
                    "only."
                )
            if payload_type is AskComparisonPayload:
                return (
                    "The previous response violated the strict Ask Database Comparison schema. "
                    "Regenerate from the original input. The top-level object must contain "
                    "exactly these keys: schema_version, ask_id, decision, answer, event_ids, "
                    "claim_ids, timeline_entry_ids, conflict_ids, evidence_signal_ids, "
                    "missing_facts, rationale. Never output status, citations, cited_ids, "
                    "sources, or any alternate field. For an answerable decision, answer is a "
                    "non-empty string, missing_facts is [], and all five ID arrays are present "
                    "even when empty. Copy only Backend-supplied IDs and preserve event_ids "
                    "order. Return one complete replacement JSON object only."
                )
            if payload_type is BackwriteReconciliationPayload:
                return (
                    "The previous response violated the strict Backwrite Reconciliation schema. "
                    "Regenerate from the original input. The top-level object must contain "
                    "exactly these seven keys: schema_version, item_id, event_id, decision, "
                    "event_update, unassigned_signal_ids, rationale. event_update is mandatory: "
                    "use JSON null for no_change, or an object with exactly title, overview, "
                    "display_time, signal_ids for update. rationale is mandatory and non-empty. "
                    "Every supplied canonical Signal ID must appear exactly once across "
                    "event_update.signal_ids and unassigned_signal_ids. Never omit a required "
                    "key, and return one complete replacement JSON object only."
                )
            return (
                "The previous response violated the strict schema. Regenerate from the original "
                "input, use only Backend-supplied IDs, obey all coverage and candidate rules, and "
                "return one complete replacement JSON object only."
            )
        if error_code in {
            "PERSONALIZATION_OUTPUT_LIMIT_EXCEEDED",
            "BRIEF_OUTPUT_LIMIT_EXCEEDED",
        }:
            return (
                "The previous response exceeded the fixed output limit. Regenerate a complete "
                "replacement JSON object with materially shorter text and no optional verbosity."
            )
        if error_code in {"ANALYSIS_EMPTY_RESPONSE", "ANALYSIS_INVALID_JSON"}:
            return "Return one complete, valid JSON object only, with no prose or code fences."
        return None

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
            payload_document = self._normalize_internal_decisions(
                json.loads(content), payload_type=payload_type
            )
            payload = payload_type.model_validate(payload_document)
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
            safe_errors = [
                {
                    "location": [str(value) for value in item["loc"]],
                    "type": item["type"],
                    "message": item["msg"],
                }
                for item in error.errors(include_input=False, include_url=False)
            ]
            logger.warning(
                "intelligence response schema invalid payload=%s error_count=%d errors=%s",
                payload_type.__name__,
                len(safe_errors),
                safe_errors[:20],
            )
            raise AnalysisError(schema_error) from error
        return payload, str(document.get("model") or self.config.model), usage

    @staticmethod
    def _normalize_internal_decisions(
        document: Any, *, payload_type: type[BaseModel]
    ) -> Any:
        specifications: dict[type[BaseModel], tuple[str, tuple[str, ...], str | None]] = {
            ClaimExtractionPayload: (
                "claim",
                ("new_claims", "existing_claim_updates"),
                "evidence_signal_ids",
            ),
            TimelineReconstructionPayload: (
                "timeline",
                ("new_entries", "existing_entry_updates"),
                "claim_ids",
            ),
            ConflictAnalysisPayload: (
                "conflict",
                ("new_conflicts", "existing_conflict_updates"),
                "claim_ids",
            ),
            BaseAnalysisPayload: (
                "base",
                ("new_analyses", "existing_analysis_updates"),
                None,
            ),
        }
        specification = specifications.get(payload_type)
        if specification is None or not isinstance(document, dict):
            return document
        prefix, field_names, evidence_field = specification
        normalized = dict(document)
        decision_index = 0
        for field_name in field_names:
            items = document.get(field_name)
            if not isinstance(items, list):
                continue
            normalized_items = []
            for item in items:
                if not isinstance(item, dict):
                    normalized_items.append(item)
                    continue
                if evidence_field is not None and item.get(evidence_field) == []:
                    continue
                value = dict(item)
                if payload_type is BaseAnalysisPayload:
                    topics = value.get("topics")
                    if isinstance(topics, list):
                        normalized_topics = []
                        seen_topics: set[str] = set()
                        for topic in topics:
                            if not isinstance(topic, str):
                                continue
                            stripped = topic.strip()
                            identity = stripped.casefold()
                            if not stripped or identity in seen_topics:
                                continue
                            seen_topics.add(identity)
                            normalized_topics.append(stripped)
                            if len(normalized_topics) == 12:
                                break
                        value["topics"] = normalized_topics
                    entities = value.get("entities")
                    if isinstance(entities, list):
                        normalized_entities = []
                        seen_entities: set[tuple[str, str]] = set()
                        for entity in entities:
                            if not isinstance(entity, dict):
                                continue
                            name = entity.get("name")
                            entity_type = entity.get("entity_type")
                            if not isinstance(name, str) or not isinstance(entity_type, str):
                                continue
                            identity = (name.strip().casefold(), entity_type)
                            if not identity[0] or identity in seen_entities:
                                continue
                            seen_entities.add(identity)
                            normalized_entities.append(
                                {"name": name.strip(), "entity_type": entity_type}
                            )
                            if len(normalized_entities) == 32:
                                break
                        value["entities"] = normalized_entities
                value["decision_key"] = f"{prefix}-{decision_index:04d}"
                decision_index += 1
                normalized_items.append(value)
            normalized[field_name] = normalized_items
        return normalized
