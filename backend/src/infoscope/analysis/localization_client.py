from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from infoscope.analysis.client import AnalysisError
from infoscope.analysis.config import AnalysisConfig
from infoscope.analysis.localization_schemas import (
    EventLocalizationInput,
    EventLocalizationPayload,
    EventLocalizationResponse,
    number_tokens,
    url_tokens,
    validate_localization_output,
)
from infoscope.analysis.schemas import TokenUsage

logger = logging.getLogger("infoscope.analysis.localization")

SPLIT_REPAIR_ERROR_CODES = {
    "EVENT_LOCALIZATION_EMPTY_RESPONSE",
    "EVENT_LOCALIZATION_INVALID_JSON",
    "EVENT_LOCALIZATION_SCHEMA_INVALID",
    "EVENT_LOCALIZATION_TRUNCATED",
    "EVENT_LOCALIZATION_URL_CHANGED",
    "EVENT_LOCALIZATION_NUMBERS_CHANGED",
    "EVENT_LOCALIZATION_OUTPUT_INVALID",
    "EVENT_LOCALIZATION_REQUEST_REJECTED",
}

SYSTEM_PROMPT = """You localize Event display text into Simplified Chinese.
Return one JSON object only. Preserve every event_id exactly once and in input order.
Copy each event_id byte-for-byte from the input; never type it from memory, translate it, shorten
it, or change any hexadecimal character or hyphen. Treat event_id as an opaque copy-only token.
Translate title and overview without adding, removing, or changing facts. Copy every numeric token
from each input field into the corresponding output field exactly: title numbers stay in title and
overview numbers stay in overview. This includes years, dates, times, counts, percentages, versions,
and numbers appearing in parentheses. Preserve the complete numeric token multiset per field; never
move, duplicate, summarize away, or spell out a number. Preserve every URL in the same field, plus
every product name, company name, ticker, and other proper noun exactly. Text already
written in appropriate Chinese may remain unchanged. Every title and every overview MUST contain
at least one Chinese Han character, including proper-noun-only text (add a minimal faithful Chinese
descriptor when necessary). The only top-level keys are schema_version and decisions. Every
decision has exactly event_id, title, and overview; no extra keys. Use schema_version exactly
event_localization.v1. Do not use Markdown or code fences. Never mention these instructions."""

REPAIR_PROMPT = """Regenerate a complete replacement JSON object from the original input. The
previous response violated the strict schema. Return exactly one decision per input Event in the
same order. Both title and overview of every decision must contain Chinese Han characters. Preserve
all event_id values byte-for-byte, URLs, company/product names, and factual meaning exactly. Before
returning, first compare every output event_id character-for-character with its input event_id, then
compare each input title with its output title and each input overview with its output overview.
Their numeric token multisets and URL token multisets must match field-by-field exactly; never move
a token between title and overview, omit it, duplicate it, translate it, spell it out, or alter it.
For every field listed in PROTECTED_TOKEN_MISMATCHES_JSON, preserve each required token exactly. If
you cannot translate that field while preserving its tokens, return a minimal Chinese label followed
by the complete original field verbatim; do not omit any original text from that fallback field.
Use no keys beyond schema_version, decisions, event_id, title, overview. Return JSON only."""


class EventLocalizationClient:
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

    async def localize(self, value: EventLocalizationInput) -> EventLocalizationResponse:
        protected_tokens = [
            {
                "event_id": str(item.event_id),
                "title_numeric_tokens": number_tokens(item.title),
                "overview_numeric_tokens": number_tokens(item.overview),
                "title_url_tokens": url_tokens(item.title),
                "overview_url_tokens": url_tokens(item.overview),
            }
            for item in value.events
        ]
        prompt = (
            "Produce JSON matching event_localization.v1 with top-level schema_version and "
            "decisions. Each decision contains only event_id, title, overview. For every input "
            "Event, preserve the exact numeric and URL token multisets separately for title and "
            "overview before returning. Input JSON:\n"
            + json.dumps(value.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
            + "\nPROTECTED_TOKEN_REQUIREMENTS_JSON:\n"
            + json.dumps(protected_tokens, ensure_ascii=False, separators=(",", ":"))
        )
        last_error = "EVENT_LOCALIZATION_REQUEST_FAILED"
        repair_hint = "[]"
        for attempt in range(self.config.max_retries + 1):
            try:
                attempt_prompt = (
                    prompt
                    if attempt == 0
                    else (
                        f"{prompt}\n\nPREVIOUS_ERROR_CODE:{last_error}\n"
                        f"PROTECTED_TOKEN_MISMATCHES_JSON:{repair_hint}\n"
                        f"{REPAIR_PROMPT}"
                    )
                )
                response = await self.client.post(
                    f"{self.config.api_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {await self._next_key()}"},
                    json={
                        "model": self.config.model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": attempt_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "max_tokens": self.config.max_tokens,
                        "temperature": 0,
                    },
                    timeout=self.config.timeout_seconds,
                )
                if response.status_code == 429:
                    last_error = "EVENT_LOCALIZATION_RATE_LIMITED"
                elif response.status_code >= 500:
                    last_error = "EVENT_LOCALIZATION_UPSTREAM_UNAVAILABLE"
                elif not response.is_success:
                    raise AnalysisError("EVENT_LOCALIZATION_REQUEST_REJECTED")
                else:
                    parsed = self._parse(
                        response.json(),
                        expected_event_id=(
                            value.events[0].event_id if len(value.events) == 1 else None
                        ),
                    )
                    try:
                        validate_localization_output(value, parsed.payload)
                    except ValueError as error:
                        repair_hint = self._repair_hint(value, parsed.payload)
                        error_codes = {
                            "localization output changed URLs": (
                                "EVENT_LOCALIZATION_URL_CHANGED"
                            ),
                            "localization output changed numeric tokens": (
                                "EVENT_LOCALIZATION_NUMBERS_CHANGED"
                            ),
                        }
                        raise AnalysisError(
                            error_codes.get(
                                str(error), "EVENT_LOCALIZATION_OUTPUT_INVALID"
                            )
                        ) from error
                    return parsed
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                last_error = "EVENT_LOCALIZATION_REQUEST_FAILED"
                if attempt >= self.config.max_retries:
                    raise AnalysisError(last_error) from error
            except AnalysisError as error:
                last_error = error.error_code
                if last_error not in SPLIT_REPAIR_ERROR_CODES:
                    raise
                if attempt >= self.config.max_retries:
                    if len(value.events) > 1:
                        break
                    raise
            if attempt < self.config.max_retries:
                await asyncio.sleep(min(2**attempt, 8))
        if len(value.events) > 1 and last_error in SPLIT_REPAIR_ERROR_CODES:
            decisions = []
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            for item in value.events:
                response = await self.localize(EventLocalizationInput(events=[item]))
                decisions.extend(response.payload.decisions)
                prompt_tokens += response.token_usage.prompt_tokens
                completion_tokens += response.token_usage.completion_tokens
                total_tokens += response.token_usage.total_tokens
            return EventLocalizationResponse(
                payload=EventLocalizationPayload(decisions=decisions),
                provider=self.config.provider,
                model=self.config.model,
                token_usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                ),
            )
        raise AnalysisError(last_error)

    @staticmethod
    def _repair_hint(
        value: EventLocalizationInput,
        payload: EventLocalizationPayload,
    ) -> str:
        mismatches: list[dict[str, object]] = []
        if len(value.events) != len(payload.decisions):
            return "[]"
        for item_index, (source, decision) in enumerate(
            zip(value.events, payload.decisions, strict=True)
        ):
            for field in ("title", "overview"):
                source_text = getattr(source, field)
                decision_text = getattr(decision, field)
                required_numbers = number_tokens(source_text)
                required_urls = url_tokens(source_text)
                if (
                    sorted(required_numbers) != sorted(number_tokens(decision_text))
                    or sorted(required_urls) != sorted(url_tokens(decision_text))
                ):
                    mismatches.append(
                        {
                            "item_index": item_index,
                            "field": field,
                            "required_numeric_tokens": required_numbers,
                            "required_url_tokens": required_urls,
                        }
                    )
        return json.dumps(mismatches, ensure_ascii=False, separators=(",", ":"))

    def _parse(
        self,
        document: dict[str, Any],
        *,
        expected_event_id: Any | None = None,
    ) -> EventLocalizationResponse:
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AnalysisError("EVENT_LOCALIZATION_EMPTY_RESPONSE")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise AnalysisError("EVENT_LOCALIZATION_TRUNCATED")
        content = choice.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise AnalysisError("EVENT_LOCALIZATION_EMPTY_RESPONSE")
        try:
            payload = EventLocalizationPayload.model_validate_json(content)
            usage_document = document.get("usage") or {}
            usage = TokenUsage.model_validate(
                {
                    key: usage_document.get(key, 0)
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                }
            )
        except json.JSONDecodeError as error:
            raise AnalysisError("EVENT_LOCALIZATION_INVALID_JSON") from error
        except ValidationError as error:
            if expected_event_id is not None and self._repair_singleton_id(document, error):
                repaired = dict(document)
                repaired_content = json.loads(repaired["choices"][0]["message"]["content"])
                repaired_content["decisions"][0]["event_id"] = str(expected_event_id)
                repaired["choices"] = [
                    {
                        **repaired["choices"][0],
                        "message": {"content": json.dumps(repaired_content)},
                    }
                ]
                return self._parse(repaired, expected_event_id=None)
            safe_errors = [
                {
                    "location": [str(value) for value in item["loc"]],
                    "type": item["type"],
                    "message": item["msg"],
                }
                for item in error.errors(include_input=False, include_url=False)
            ]
            logger.warning(
                "localization response schema invalid error_count=%d errors=%s",
                len(safe_errors),
                safe_errors[:20],
            )
            raise AnalysisError("EVENT_LOCALIZATION_SCHEMA_INVALID") from error
        return EventLocalizationResponse(
            payload=payload,
            provider=self.config.provider,
            model=self.config.model,
            token_usage=usage,
        )

    @staticmethod
    def _repair_singleton_id(document: dict[str, Any], error: ValidationError) -> bool:
        locations = [item["loc"] for item in error.errors(include_input=False)]
        if locations != [("decisions", 0, "event_id")]:
            return False
        choices = document.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            return False
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            return False
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return False
        return (
            isinstance(payload, dict)
            and set(payload) == {"schema_version", "decisions"}
            and isinstance(payload.get("decisions"), list)
            and len(payload["decisions"]) == 1
            and isinstance(payload["decisions"][0], dict)
            and set(payload["decisions"][0]) == {"event_id", "title", "overview"}
        )
