from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.prompt import SYSTEM_PROMPT, build_user_prompt
from infoscope.analysis.schemas import (
    AnalysisResponse,
    AnalysisSignal,
    TokenUsage,
    WindowAnalysisModelPayload,
)
from infoscope.pipeline import LogicalWindow

logger = logging.getLogger("infoscope.analysis.window")


class AnalysisError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class DeepSeekAnalysisClient:
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

    async def analyze(
        self,
        *,
        window: LogicalWindow,
        signals: list[AnalysisSignal],
    ) -> AnalysisResponse:
        last_error = "ANALYSIS_REQUEST_FAILED"
        for attempt in range(self.config.max_retries + 1):
            key = await self._next_key()
            try:
                user_prompt = build_user_prompt(window=window, signals=signals)
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
                response = await self.client.post(
                    f"{self.config.api_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=request_payload,
                    timeout=self.config.timeout_seconds,
                )
                last_error = self._response_error(response)
                if last_error:
                    if attempt < self.config.max_retries and self._retryable(response.status_code):
                        await asyncio.sleep(min(2**attempt, 8))
                        continue
                    raise AnalysisError(last_error)
                parsed = self._parse_response(response.json())
                expected_signal_ids = {signal.signal_id for signal in signals}
                actual_signal_ids = {
                    item.signal_id for item in parsed.payload.signal_analyses
                }
                if actual_signal_ids != expected_signal_ids:
                    raise AnalysisError("ANALYSIS_SIGNAL_COVERAGE_INVALID")
                return parsed
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

    @staticmethod
    def _repair_instruction(error_code: str) -> str | None:
        if error_code == "ANALYSIS_SCHEMA_INVALID":
            return (
                "The previous response violated the strict schema. Regenerate from the original "
                "input. Use every supplied signal_id exactly once in signal_analyses. Set exactly "
                "one cluster_key or null on each item; every non-null key must have exactly one "
                "cluster summary. Never emit signal_ids on cluster objects, never duplicate a "
                "cluster_key, use at most 4 categories and 3 fact_claims per Signal. Every "
                "relationship must contain at least 2 distinct signal_ids that are both assigned "
                "to that relationship's cluster; omit the relationship when this cannot be met. "
                "Obey every array/text limit. Return a complete replacement JSON object only."
            )
        if error_code == "ANALYSIS_SIGNAL_COVERAGE_INVALID":
            return (
                "The previous response did not cover the supplied Signal IDs exactly. Regenerate "
                "from the original input with one signal_analysis for every supplied signal_id, "
                "in the same order. Do not omit, invent, replace, or duplicate any signal_id. "
                "Return a complete replacement JSON object only."
            )
        if error_code == "ANALYSIS_TRUNCATED":
            return (
                "The previous response was truncated. Regenerate a materially more concise but "
                "complete replacement JSON object. Keep claims, summaries, relationships, and "
                "missing context well below their limits while preserving exact Signal coverage."
            )
        if error_code in {"ANALYSIS_EMPTY_RESPONSE", "ANALYSIS_INVALID_JSON"}:
            return "Return one complete, valid JSON object only, with no prose or code fences."
        return None

    @staticmethod
    def _retryable(status_code: int) -> bool:
        return status_code == 429 or status_code >= 500

    @staticmethod
    def _response_error(response: httpx.Response) -> str:
        if response.status_code == 429:
            return "ANALYSIS_RATE_LIMITED"
        if response.status_code >= 500:
            return "ANALYSIS_UPSTREAM_UNAVAILABLE"
        if not response.is_success:
            return "ANALYSIS_REQUEST_REJECTED"
        return ""

    def _parse_response(self, document: dict[str, Any]) -> AnalysisResponse:
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
            model_payload = WindowAnalysisModelPayload.model_validate(payload_document)
            payload = model_payload.to_window_payload()
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
                "analysis response schema invalid error_count=%d errors=%s",
                len(safe_errors),
                safe_errors[:20],
            )
            raise AnalysisError("ANALYSIS_SCHEMA_INVALID") from error
        return AnalysisResponse(
            payload=payload,
            provider=self.config.provider,
            model=str(document.get("model") or self.config.model),
            token_usage=usage,
        )
