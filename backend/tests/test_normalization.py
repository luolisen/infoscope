from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from infoscope.models import NormalizationStatus, RawInformation, SourceVisibility
from infoscope.services.normalization import (
    PRIVATE_SOURCE_REDACTION,
    DeterministicNormalizer,
    NormalizationError,
    NormalizationRunner,
)


def _raw(
    *,
    source_type: str,
    content_text: str | None,
    visibility: SourceVisibility = SourceVisibility.PUBLIC,
    payload: dict | None = None,
    provenance: dict | None = None,
) -> RawInformation:
    return RawInformation(
        id=uuid4(),
        source_type=source_type,
        source_key="source-key",
        source_visibility=visibility.value,
        acquired_at=datetime(2026, 8, 16, 10, tzinfo=UTC),
        published_at=datetime(2026, 8, 16, 9, tzinfo=UTC),
        content_text=content_text,
        payload=payload or {},
        provenance=provenance or {},
        collector_metadata={},
        content_hash="a" * 64,
        normalization_status=NormalizationStatus.PENDING.value,
        normalization_attempts=0,
    )


def test_telegram_normalization_preserves_text_and_allowlists_public_provenance() -> None:
    raw = _raw(
        source_type="telegram",
        content_text="  First line\r\nSecond line  ",
        provenance={
            "platform": "Telegram",
            "chat_title": "Public News",
            "chat_username": "public_news",
            "url": "https://t.me/public_news/1",
            "peer_id": -1001,
            "message_id": 1,
        },
    )

    signal = DeterministicNormalizer().normalize(raw)

    assert signal.normalized_text == "First line\nSecond line"
    assert signal.title is None
    assert signal.published_at == raw.published_at
    assert signal.public_provenance == {
        "platform": "Telegram",
        "chat_title": "Public News",
        "chat_username": "public_news",
        "url": "https://t.me/public_news/1",
    }
    assert "peer_id" not in signal.public_provenance


def test_trendradar_normalization_extracts_title_and_removes_internal_source_id() -> None:
    raw = _raw(
        source_type="trend_radar",
        content_text="Headline\nSummary",
        payload={"entry": {"title": "Headline"}},
        provenance={
            "source_kind": "rss",
            "source_id": "internal-feed-id",
            "source_name": "Example Feed",
            "url": "https://example.com/item",
        },
    )

    signal = DeterministicNormalizer().normalize(raw)

    assert signal.title == "Headline"
    assert signal.normalized_text == "Headline\nSummary"
    assert signal.public_provenance == {
        "source_kind": "rss",
        "source_name": "Example Feed",
        "url": "https://example.com/item",
    }


def test_private_telegram_body_explicitly_redacts_source_identity() -> None:
    raw = _raw(
        source_type="telegram",
        visibility=SourceVisibility.PRIVATE,
        content_text=(
            "Secret Alpha posted in -1001234567890. "
            "Invite: https://t.me/+PrivateInviteCode and ping @secret_alpha"
        ),
        provenance={
            "platform": "Telegram",
            "chat_title": "Secret Alpha",
            "chat_username": "secret_alpha",
            "peer_id": -1001234567890,
        },
    )

    signal = DeterministicNormalizer().normalize(raw)

    assert signal.public_provenance is None
    assert signal.normalized_text.count(PRIVATE_SOURCE_REDACTION) == 4
    assert "Secret Alpha" not in signal.normalized_text
    assert "secret_alpha" not in signal.normalized_text
    assert "PrivateInviteCode" not in signal.normalized_text
    assert "1001234567890" not in signal.normalized_text


@pytest.mark.parametrize(
    ("source_type", "content", "error_code"),
    [
        ("unknown", "text", "NORMALIZE_UNSUPPORTED_SOURCE"),
        ("telegram", "  ", "NORMALIZE_EMPTY_CONTENT"),
        ("telegram", None, "NORMALIZE_EMPTY_CONTENT"),
    ],
)
def test_normalization_rejects_unsupported_or_empty_raw(
    source_type: str,
    content: str | None,
    error_code: str,
) -> None:
    with pytest.raises(NormalizationError) as captured:
        DeterministicNormalizer().normalize(
            _raw(source_type=source_type, content_text=content)
        )

    assert captured.value.error_code == error_code


class FakeRepository:
    def __init__(self, raws: list[RawInformation]) -> None:
        self.raws = raws
        self.started: list[RawInformation] = []
        self.failed: list[tuple[RawInformation, str]] = []
        self.signals: list[object] = []

    async def list_raw_for_normalization(
        self, *, retry_failed: bool, limit: int
    ) -> list[RawInformation]:
        return self.raws[:limit]

    async def mark_normalization_started(self, raw: RawInformation) -> None:
        self.started.append(raw)

    async def mark_normalization_failed(self, raw: RawInformation, *, error_code: str) -> None:
        self.failed.append((raw, error_code))

    async def persist_signal(self, *, raw, value, normalized_at):
        self.signals.append(value)
        return SimpleNamespace()


async def test_runner_isolates_deterministic_failures_and_continues() -> None:
    valid = _raw(source_type="telegram", content_text="Valid")
    empty = _raw(source_type="telegram", content_text=" ")
    repository = FakeRepository([valid, empty])

    result = await NormalizationRunner(repository=repository).run_once(  # type: ignore[arg-type]
        limit=10
    )

    assert result.processed == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert repository.started == [valid, empty]
    assert repository.failed == [(empty, "NORMALIZE_EMPTY_CONTENT")]
    assert len(repository.signals) == 1
