from datetime import UTC, datetime, timedelta
from uuid import uuid4

from infoscope.models import EvidenceVisibility, Signal
from infoscope.services.deduplication import ExactDeduplicationRunner


def _signal(*, content_hash: str, created_at: datetime) -> Signal:
    return Signal(
        id=uuid4(),
        raw_information_id=uuid4(),
        signal_index=0,
        normalized_text="normalized",
        source_type="telegram",
        evidence_visibility=EvidenceVisibility.PUBLIC.value,
        public_provenance=None,
        content_hash=content_hash,
        created_at=created_at,
    )


class FakeRepository:
    def __init__(self, signals: list[Signal]) -> None:
        self.signals = sorted(signals, key=lambda signal: (signal.created_at, signal.id))

    async def list_signals_for_deduplication(
        self,
        *,
        after_created_at,
        after_signal_id,
        limit: int,
    ) -> list[Signal]:
        candidates = [signal for signal in self.signals if signal.duplicate_of_signal_id is None]
        if after_created_at is not None:
            cursor = (after_created_at, after_signal_id)
            candidates = [
                signal
                for signal in candidates
                if (signal.created_at, signal.id) > cursor
            ]
        return candidates[:limit]

    async def find_exact_duplicate_canonical(self, signal: Signal) -> Signal | None:
        candidates = [
            candidate
            for candidate in self.signals
            if candidate.content_hash == signal.content_hash
            and candidate.duplicate_of_signal_id is None
            and (candidate.created_at, candidate.id) < (signal.created_at, signal.id)
        ]
        return min(candidates, key=lambda value: (value.created_at, value.id), default=None)

    async def mark_signal_duplicate(self, signal: Signal, *, canonical: Signal) -> None:
        signal.duplicate_of_signal_id = canonical.id


async def test_exact_duplicates_link_directly_to_the_earliest_canonical() -> None:
    started_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    canonical = _signal(content_hash="a" * 64, created_at=started_at)
    duplicate_one = _signal(
        content_hash="a" * 64,
        created_at=started_at + timedelta(seconds=1),
    )
    unique = _signal(
        content_hash="b" * 64,
        created_at=started_at + timedelta(seconds=2),
    )
    duplicate_two = _signal(
        content_hash="a" * 64,
        created_at=started_at + timedelta(seconds=3),
    )
    repository = FakeRepository([duplicate_two, unique, duplicate_one, canonical])

    result = await ExactDeduplicationRunner(repository=repository).run(  # type: ignore[arg-type]
        batch_size=2
    )

    assert result.scanned == 4
    assert result.duplicates_linked == 2
    assert canonical.duplicate_of_signal_id is None
    assert unique.duplicate_of_signal_id is None
    assert duplicate_one.duplicate_of_signal_id == canonical.id
    assert duplicate_two.duplicate_of_signal_id == canonical.id


async def test_exact_deduplication_is_idempotent() -> None:
    started_at = datetime(2026, 8, 16, 10, tzinfo=UTC)
    canonical = _signal(content_hash="a" * 64, created_at=started_at)
    duplicate = _signal(
        content_hash="a" * 64,
        created_at=started_at + timedelta(seconds=1),
    )
    repository = FakeRepository([canonical, duplicate])
    runner = ExactDeduplicationRunner(repository=repository)  # type: ignore[arg-type]

    first = await runner.run(batch_size=1)
    second = await runner.run(batch_size=1)

    assert first.duplicates_linked == 1
    assert second.scanned == 1
    assert second.duplicates_linked == 0
    assert duplicate.duplicate_of_signal_id == canonical.id
