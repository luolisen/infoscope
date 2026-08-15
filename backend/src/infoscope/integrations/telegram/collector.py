from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Protocol

from infoscope.integrations.telegram.client import TelegramSourceError
from infoscope.integrations.telegram.models import (
    CollectionFailure,
    CollectionResult,
    TelegramDialog,
    TelegramMessage,
)
from infoscope.models import SourceVisibility
from infoscope.services.acquisition import AcquisitionRepository, RawInformationInput


class TelegramClientProtocol(Protocol):
    async def folder_dialogs(self) -> list[TelegramDialog]: ...

    def iter_messages(
        self, dialog: TelegramDialog, *, after_message_id: int | None
    ) -> AsyncIterator[TelegramMessage]: ...


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload(message: TelegramMessage) -> dict[str, object]:
    return {
        "message_id": message.id,
        "text": message.text,
        "published_at": message.published_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "sender_id": message.sender_id,
        "reply_to_message_id": message.reply_to_message_id,
        "grouped_id": message.grouped_id,
        "media_type": message.media_type,
        "views": message.views,
        "forwards": message.forwards,
    }


class TelegramCollector:
    def __init__(
        self,
        *,
        client: TelegramClientProtocol,
        repository: AcquisitionRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.repository = repository
        self.clock = clock

    async def collect(self) -> CollectionResult:
        dialogs = await self.client.folder_dialogs()
        inserted = 0
        duplicates = 0
        failures: list[CollectionFailure] = []

        for dialog in dialogs:
            after = await self.repository.latest_telegram_message_id(peer_id=dialog.peer_id)
            try:
                async for message in self.client.iter_messages(dialog, after_message_id=after):
                    persisted = await self.repository.persist_raw(self._raw(dialog, message))
                    if persisted.inserted:
                        inserted += 1
                    else:
                        duplicates += 1
            except TelegramSourceError as error:
                failures.append(CollectionFailure(error_code=error.error_code))

        return CollectionResult(
            dialogs=len(dialogs),
            inserted=inserted,
            duplicates=duplicates,
            failures=tuple(failures),
        )

    def _raw(self, dialog: TelegramDialog, message: TelegramMessage) -> RawInformationInput:
        payload = _payload(message)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        public_url = (
            f"https://t.me/{dialog.username}/{message.id}" if dialog.username is not None else None
        )
        return RawInformationInput(
            source_type="telegram",
            source_key=_sha256(f"{dialog.peer_id}:{message.id}"),
            source_visibility=(
                SourceVisibility.PUBLIC if dialog.is_public else SourceVisibility.PRIVATE
            ),
            acquired_at=self.clock(),
            published_at=message.published_at,
            content_text=message.text,
            payload=payload,
            provenance={
                "platform": "Telegram",
                "chat_title": dialog.title,
                "chat_username": dialog.username,
                "peer_id": dialog.peer_id,
                "message_id": message.id,
                "url": public_url,
            },
            collector_metadata={
                "integration": "tgnews",
                "peer_id": dialog.peer_id,
                "message_id": message.id,
            },
            content_hash=_sha256(canonical),
        )
