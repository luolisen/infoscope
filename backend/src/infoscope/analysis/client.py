from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import ValidationError

from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.prompt import SYSTEM_PROMPT, build_user_prompt
from infoscope.analysis.schemas import (
    AnalysisResponse,
    AnalysisSignal,
    TokenUsage,
    WindowAnalysisPayload,
)
from infoscope.pipeline import LogicalWindow


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
                response = await self.client.post(
                    f"{self.config.api_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": self.config.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": build_user_prompt(window=window, signals=signals),
                            },
                        ],
                        "response_format": {"type": "json_object"},
                        "thinking": {"type": "enabled"},
                        "max_tokens": self.config.max_tokens,
                        "temperature": 0,
                    },
                    timeout=self.config.timeout_seconds,
                )
                last_error = self._response_error(response)
                if last_error:
                    if attempt < self.config.max_retries and self._retryable(response.status_code):
                        await asyncio.sleep(min(2**attempt, 8))
                        continue
                    raise AnalysisError(last_error)
                return self._parse_response(response.json())
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
                    "ANALYSIS_TRUNCATED",
                }:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
        raise AnalysisError(last_error)

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
            payload = WindowAnalysisPayload.model_validate(payload_document)
            usage_document = document.get("usage") or {}
            usage = TokenUsage.model_validate(
                {
                    key: usage_document.get(key, 0)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            )
        except ValidationError as error:
            raise AnalysisError("ANALYSIS_SCHEMA_INVALID") from error
        return AnalysisResponse(
            payload=payload,
            provider="deepseek",
            model=str(document.get("model") or self.config.model),
            token_usage=usage,
        )
