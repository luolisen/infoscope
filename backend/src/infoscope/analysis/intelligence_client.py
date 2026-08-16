from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.intelligence_prompt import (
    CLAIM_SYSTEM_PROMPT,
    TIMELINE_SYSTEM_PROMPT,
    build_claim_prompt,
    build_timeline_prompt,
)
from infoscope.analysis.intelligence_schemas import (
    ClaimExtractionPayload,
    ClaimExtractionResponse,
    ClaimTimelineInput,
    EventClaimInput,
    ExistingClaimCandidate,
    ExistingTimelineCandidate,
    TimelineReconstructionPayload,
    TimelineReconstructionResponse,
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
        self, *, claims: list[ClaimTimelineInput], candidates: list[ExistingTimelineCandidate]
    ) -> TimelineReconstructionResponse:
        payload, model, usage = await self._request(
            system=TIMELINE_SYSTEM_PROMPT,
            user=build_timeline_prompt(claims, candidates),
            payload_type=TimelineReconstructionPayload,
        )
        return TimelineReconstructionResponse(
            payload=payload, provider="deepseek", model=model, token_usage=usage
        )

    async def _next_key(self) -> str:
        async with self._key_lock:
            key = self.config.api_keys[self._key_index % len(self.config.api_keys)]
            self._key_index += 1
            return key

    async def _request(
        self, *, system: str, user: str, payload_type: type[PayloadT]
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
                return self._parse(response.json(), payload_type)
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
                }:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
        raise AnalysisError("ANALYSIS_REQUEST_FAILED")

    def _parse(
        self, document: dict[str, Any], payload_type: type[PayloadT]
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
            raise AnalysisError("ANALYSIS_SCHEMA_INVALID") from error
        return payload, str(document.get("model") or self.config.model), usage
