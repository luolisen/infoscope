from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class CollectedItem:
    source_kind: str
    source_id: str
    source_name: str
    stable_id: str
    title: str
    url: str
    published_at: datetime | None
    payload: dict[str, Any]
    collector_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceFailure:
    source_id: str
    error_code: str


@dataclass(frozen=True, slots=True)
class CollectionResult:
    inserted: int
    duplicates: int
    failures: tuple[SourceFailure, ...]
