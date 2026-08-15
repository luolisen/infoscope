from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from infoscope.services.acquisition import AcquisitionRepository


@dataclass(frozen=True, slots=True)
class DeduplicationCursor:
    created_at: datetime
    signal_id: UUID


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    scanned: int
    duplicates_linked: int


class ExactDeduplicationRunner:
    """Link exact normalized-text duplicates without reconstructing Events."""

    def __init__(self, *, repository: AcquisitionRepository) -> None:
        self.repository = repository

    async def run(self, *, batch_size: int = 500) -> DeduplicationResult:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        scanned = 0
        duplicates_linked = 0
        cursor: DeduplicationCursor | None = None

        while True:
            signals = await self.repository.list_signals_for_deduplication(
                after_created_at=cursor.created_at if cursor else None,
                after_signal_id=cursor.signal_id if cursor else None,
                limit=batch_size,
            )
            if not signals:
                break
            for signal in signals:
                if signal.created_at is None:
                    raise ValueError("persisted Signal must have created_at")
                scanned += 1
                canonical = await self.repository.find_exact_duplicate_canonical(signal)
                if canonical is not None:
                    await self.repository.mark_signal_duplicate(signal, canonical=canonical)
                    duplicates_linked += 1
                cursor = DeduplicationCursor(signal.created_at, signal.id)
            if len(signals) < batch_size:
                break

        return DeduplicationResult(scanned=scanned, duplicates_linked=duplicates_linked)
