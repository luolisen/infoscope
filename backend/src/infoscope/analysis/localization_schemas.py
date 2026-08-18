from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from infoscope.analysis.schemas import StrictModel, TokenUsage

INPUT_SCHEMA_VERSION = "event_localization_input.v1"
OUTPUT_SCHEMA_VERSION = "event_localization.v1"
LOCALE = "zh-CN"
MAX_BATCH_EVENTS = 10
MAX_CANONICAL_BYTES = 128_000
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:[.,:/-]\d+)*(?![\w])")
_URL_TRAILING_PUNCTUATION = ".,;:!?)]}，。；：！？）】》"


def canonical_bytes(value: StrictModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: StrictModel) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def url_tokens(value: str) -> list[str]:
    return [item.rstrip(_URL_TRAILING_PUNCTUATION) for item in _URL.findall(value)]


def number_tokens(value: str) -> list[str]:
    return _NUMBER.findall(value)


class EventLocalizationItem(StrictModel):
    event_id: UUID
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)
    state: Literal["developing", "confirmed", "conflicting", "cooling"]
    display_time: datetime
    updated_at: datetime

    @field_validator("title", "overview")
    @classmethod
    def text_is_bounded(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized.encode("utf-8")) > 32_000:
            raise ValueError("localization input text exceeds its UTF-8 byte limit")
        return normalized


class EventLocalizationInput(StrictModel):
    schema_version: Literal["event_localization_input.v1"] = INPUT_SCHEMA_VERSION
    locale: Literal["zh-CN"] = LOCALE
    events: list[EventLocalizationItem] = Field(min_length=1, max_length=MAX_BATCH_EVENTS)

    @model_validator(mode="after")
    def events_are_unique_and_ordered(self) -> EventLocalizationInput:
        ids = [item.event_id for item in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("localization events must be unique")
        if ids != sorted(ids):
            raise ValueError("localization events must use Backend UUID order")
        if len(canonical_bytes(self)) > MAX_CANONICAL_BYTES:
            raise ValueError("localization input exceeds its canonical byte limit")
        return self


class EventLocalizationDecision(StrictModel):
    event_id: UUID
    title: str = Field(min_length=1, max_length=512)
    overview: str = Field(min_length=1, max_length=8000)

    @field_validator("title", "overview")
    @classmethod
    def localized_text_is_chinese_and_bounded(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized.encode("utf-8")) > 32_000:
            raise ValueError("localized text exceeds its UTF-8 byte limit")
        if _CJK.search(normalized) is None:
            raise ValueError("localized text must contain Chinese")
        return normalized


class EventLocalizationPayload(StrictModel):
    schema_version: Literal["event_localization.v1"] = OUTPUT_SCHEMA_VERSION
    decisions: list[EventLocalizationDecision] = Field(min_length=1, max_length=MAX_BATCH_EVENTS)


class EventLocalizationResponse(StrictModel):
    payload: EventLocalizationPayload
    provider: str
    model: str
    token_usage: TokenUsage


def validate_localization_output(
    original: EventLocalizationInput,
    payload: EventLocalizationPayload,
) -> None:
    expected = [item.event_id for item in original.events]
    actual = [item.event_id for item in payload.decisions]
    if actual != expected or len(actual) != len(set(actual)):
        raise ValueError("localization output must preserve exact Event coverage and order")
    for source, decision in zip(original.events, payload.decisions, strict=True):
        for original_text, localized_text in (
            (source.title, decision.title),
            (source.overview, decision.overview),
        ):
            if sorted(url_tokens(original_text)) != sorted(url_tokens(localized_text)):
                raise ValueError("localization output changed URLs")
            if sorted(number_tokens(original_text)) != sorted(number_tokens(localized_text)):
                raise ValueError("localization output changed numeric tokens")
