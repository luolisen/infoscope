from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.reconstruction_prompt import (
    SYSTEM_PROMPT,
    build_reconstruction_prompt,
)
from infoscope.analysis.reconstruction_schemas import (
    RECONSTRUCTION_MODEL_SCHEMA_VERSION,
    EventReconstructionModelPayload,
    EventReconstructionPayload,
    EventReconstructionResponse,
    ExistingEventCandidate,
    NewEventModelDecision,
)
from infoscope.analysis.request_transport import (
    TransientRequestFailure,
    post_with_key_failover,
)
from infoscope.analysis.schemas import AnalysisSignal, TokenUsage, WindowAnalysisPayload

logger = logging.getLogger("infoscope.analysis.event_reconstruction")


class DeepSeekEventReconstructionClient:
    def __init__(self, *, client: httpx.AsyncClient, config: AnalysisConfig) -> None:
        self.client = client
        self.config = config
        self._key_index = 0
        self._key_lock = asyncio.Lock()

    async def _next_key(self) -> str:
        async with self._key_lock:
            key = self.config.api_keys[self._key_index % len(self.config.api_keys)]
            self._key_index += 1
            return key

    async def reconstruct(
        self,
        *,
        window_analysis: WindowAnalysisPayload,
        signals: list[AnalysisSignal],
        candidates: list[ExistingEventCandidate],
    ) -> EventReconstructionResponse:
        last_error = "ANALYSIS_REQUEST_FAILED"
        for attempt in range(self.config.max_retries + 1):
            key = await self._next_key()
            try:
                user_prompt = build_reconstruction_prompt(
                    window_analysis=window_analysis,
                    signals=signals,
                    candidates=candidates,
                )
                repair_instruction = self._repair_instruction(last_error)
                if attempt > 0 and repair_instruction is not None:
                    user_prompt = f"{user_prompt}\n\n{repair_instruction}"
                request_payload: dict[str, Any] = {
                    "model": self.config.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": self.config.max_tokens,
                    "temperature": 0,
                }
                if self.config.supports_deepseek_thinking:
                    request_payload["thinking"] = {"type": "disabled"}
                response = await self._post(request_payload, first_key=key)
                if not response.is_success:
                    raise AnalysisError("ANALYSIS_REQUEST_REJECTED")
                return self._parse_response(
                    response.json(),
                    signal_ids=[signal.signal_id for signal in signals],
                    candidate_ids={candidate.event_id for candidate in candidates},
                )
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                last_error = "ANALYSIS_REQUEST_FAILED"
                if attempt >= self.config.max_retries:
                    raise AnalysisError(last_error) from error
                await asyncio.sleep(min(2**attempt, 8))
            except AnalysisError as error:
                last_error = error.error_code
                if attempt >= self.config.max_retries or error.error_code not in {
                    "ANALYSIS_EMPTY_RESPONSE",
                    "ANALYSIS_INVALID_JSON",
                    "ANALYSIS_SCHEMA_INVALID",
                    "ANALYSIS_SIGNAL_COVERAGE_INVALID",
                    "ANALYSIS_TRUNCATED",
                }:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
        raise AnalysisError(last_error)

    async def _post(
        self, request_payload: dict[str, Any], *, first_key: str
    ) -> httpx.Response:
        used_first = False

        async def next_key() -> str:
            nonlocal used_first
            if not used_first:
                used_first = True
                return first_key
            return await self._next_key()

        try:
            return await post_with_key_failover(
                client=self.client,
                config=self.config,
                next_key=next_key,
                payload=request_payload,
            )
        except TransientRequestFailure as error:
            codes = {
                "request": "ANALYSIS_REQUEST_FAILED",
                "rate_limited": "ANALYSIS_RATE_LIMITED",
                "upstream_unavailable": "ANALYSIS_UPSTREAM_UNAVAILABLE",
            }
            raise AnalysisError(codes[error.kind]) from error

    @staticmethod
    def _repair_instruction(error_code: str) -> str | None:
        if error_code == "ANALYSIS_TRUNCATED":
            return (
                "The previous response was truncated. Regenerate a materially more concise but "
                "complete replacement JSON object. Preserve exact coverage of every supplied "
                "signal_id, keep titles, overviews, and rationales well below their limits, and "
                "omit all optional verbosity. Do not emit prose or code fences."
            )
        if error_code == "ANALYSIS_SCHEMA_INVALID":
            return (
                "The previous response violated the strict schema. Regenerate from the original "
                "input using event_reconstruction_model.v2. new_events and "
                "existing_event_updates must be JSON objects keyed by unique decision_key; do not "
                "emit decision_key fields or signal_ids arrays inside them. signal_assignments "
                "maps assigned supplied Signal UUID keys to one declared decision_key. Omit "
                "unassigned Signals and unused decisions. Use each existing_event_id in at most "
                "one update. Return one complete replacement JSON object only."
            )
        if error_code == "ANALYSIS_SIGNAL_COVERAGE_INVALID":
            return (
                "The previous signal_assignments object contained an unknown Signal UUID. "
                "Regenerate using only supplied Signal UUID keys. Map assigned Signals to one "
                "declared decision_key and omit unassigned Signals. Return one complete "
                "replacement JSON object only."
            )
        if error_code in {"ANALYSIS_EMPTY_RESPONSE", "ANALYSIS_INVALID_JSON"}:
            return "Return one complete, valid JSON object only, with no prose or code fences."
        return None

    def _parse_response(
        self,
        document: dict[str, Any],
        *,
        signal_ids: list[UUID],
        candidate_ids: set[UUID] | None = None,
    ) -> EventReconstructionResponse:
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AnalysisError("ANALYSIS_EMPTY_RESPONSE")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise AnalysisError("ANALYSIS_TRUNCATED")
        content = choice.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise AnalysisError("ANALYSIS_EMPTY_RESPONSE")
        try:
            payload_document = json.loads(content)
        except json.JSONDecodeError as error:
            raise AnalysisError("ANALYSIS_INVALID_JSON") from error
        try:
            if payload_document.get("schema_version") == RECONSTRUCTION_MODEL_SCHEMA_VERSION:
                model_payload = EventReconstructionModelPayload.model_validate(payload_document)
                expected_signal_ids = set(signal_ids)
                unknown_count = len(
                    set(model_payload.signal_assignments) - expected_signal_ids
                )
                if unknown_count:
                    logger.warning(
                        "event reconstruction rejected unknown signal assignments count=%d",
                        unknown_count,
                    )
                    raise AnalysisError("ANALYSIS_SIGNAL_COVERAGE_INVALID")
                if candidate_ids is not None:
                    new_events = dict(model_payload.new_events)
                    existing_updates = {}
                    converted = 0
                    for decision_key, decision in (
                        model_payload.existing_event_updates.items()
                    ):
                        if decision.existing_event_id in candidate_ids:
                            existing_updates[decision_key] = decision
                        else:
                            converted += 1
                            new_events[decision_key] = NewEventModelDecision(
                                **decision.model_dump(exclude={"existing_event_id"})
                            )
                    if converted:
                        logger.warning(
                            "event reconstruction converted unknown candidate updates count=%d",
                            converted,
                        )
                        model_payload = model_payload.model_copy(
                            update={
                                "new_events": new_events,
                                "existing_event_updates": existing_updates,
                            }
                        )
                declared_keys = {
                    *model_payload.new_events,
                    *model_payload.existing_event_updates,
                }
                unknown_target_count = sum(
                    decision_key not in declared_keys
                    for decision_key in model_payload.signal_assignments.values()
                )
                if unknown_target_count:
                    logger.warning(
                        "event reconstruction normalized unknown decision assignments count=%d",
                        unknown_target_count,
                    )
                payload = model_payload.to_event_payload(signal_ids)
            else:
                payload = EventReconstructionPayload.model_validate(payload_document)
            usage_document = document.get("usage") or {}
            usage = TokenUsage.model_validate(
                {
                    key: usage_document.get(key, 0)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            )
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
                "event reconstruction response schema invalid error_count=%d errors=%s",
                len(safe_errors),
                safe_errors[:20],
            )
            raise AnalysisError("ANALYSIS_SCHEMA_INVALID") from error
        return EventReconstructionResponse(
            payload=payload,
            provider=self.config.provider,
            model=str(document.get("model") or self.config.model),
            token_usage=usage,
        )
