from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    api_id: int
    api_hash: str = field(repr=False)
    phone: str | None
    session_path: Path
    folder_title: str
    initial_message_limit: int


@dataclass(frozen=True, slots=True)
class TelegramDialog:
    peer_id: int
    title: str
    username: str | None
    input_entity: Any = field(repr=False)

    @property
    def is_public(self) -> bool:
        return self.username is not None


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    id: int
    text: str
    published_at: datetime
    edited_at: datetime | None
    sender_id: int | None
    reply_to_message_id: int | None
    grouped_id: int | None
    media_type: str | None
    views: int | None
    forwards: int | None


@dataclass(frozen=True, slots=True)
class CollectionFailure:
    error_code: str


@dataclass(frozen=True, slots=True)
class CollectionResult:
    dialogs: int
    inserted: int
    duplicates: int
    failures: tuple[CollectionFailure, ...]
