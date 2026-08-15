from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace

from infoscope.integrations.telegram.collector import TelegramCollector
from infoscope.integrations.telegram.models import TelegramDialog, TelegramMessage
from infoscope.models import SourceVisibility


class FakeClient:
    def __init__(self, dialogs: list[TelegramDialog]) -> None:
        self.dialogs = dialogs
        self.after_values: list[int | None] = []

    async def folder_dialogs(self) -> list[TelegramDialog]:
        return self.dialogs

    async def iter_messages(
        self, dialog: TelegramDialog, *, after_message_id: int | None
    ) -> AsyncIterator[TelegramMessage]:
        self.after_values.append(after_message_id)
        yield TelegramMessage(
            id=43,
            text=f"message from {dialog.title}",
            published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
            edited_at=None,
            sender_id=7,
            reply_to_message_id=None,
            grouped_id=None,
            media_type=None,
            views=10,
            forwards=2,
        )


class FakeRepository:
    def __init__(self) -> None:
        self.values: list[object] = []

    async def latest_telegram_message_id(self, *, peer_id: int) -> int | None:
        return 42 if peer_id == 100 else None

    async def persist_raw(self, value: object) -> SimpleNamespace:
        self.values.append(value)
        return SimpleNamespace(inserted=True)


async def test_collector_uses_incremental_cursor_and_visibility_policy() -> None:
    dialogs = [
        TelegramDialog(100, "Public News", "public_news", object()),
        TelegramDialog(200, "Invite Only", None, object()),
    ]
    client = FakeClient(dialogs)
    repository = FakeRepository()
    acquired_at = datetime(2026, 8, 16, 10, tzinfo=UTC)

    result = await TelegramCollector(
        client=client,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        clock=lambda: acquired_at,
    ).collect()

    assert result.dialogs == 2
    assert result.inserted == 2
    assert result.failures == ()
    assert client.after_values == [42, None]
    public, private = repository.values
    assert public.source_visibility is SourceVisibility.PUBLIC  # type: ignore[attr-defined]
    assert public.provenance["url"] == "https://t.me/public_news/43"  # type: ignore[attr-defined]
    assert private.source_visibility is SourceVisibility.PRIVATE  # type: ignore[attr-defined]
    assert private.provenance["url"] is None  # type: ignore[attr-defined]
    assert private.collector_metadata == {  # type: ignore[attr-defined]
        "integration": "tgnews",
        "peer_id": 200,
        "message_id": 43,
    }
    assert private.source_key != public.source_key  # type: ignore[attr-defined]
