from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

WINDOW_DURATION = timedelta(hours=1)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True, order=True)
class AcquisitionCursor:
    acquired_at: datetime
    raw_id: UUID

    def __post_init__(self) -> None:
        _require_aware(self.acquired_at, "acquired_at")


@dataclass(frozen=True, slots=True)
class LogicalWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _require_aware(self.start, "start")
        _require_aware(self.end, "end")
        if self.end - self.start != WINDOW_DURATION:
            raise ValueError("logical windows must be exactly one hour")

    @classmethod
    def starting_at(cls, start: datetime) -> LogicalWindow:
        return cls(start=start, end=start + WINDOW_DURATION)

    def contains(self, acquired_at: datetime) -> bool:
        _require_aware(acquired_at, "acquired_at")
        return self.start <= acquired_at < self.end


def completed_windows(*, start: datetime, watermark: datetime) -> tuple[LogicalWindow, ...]:
    """Return consecutive complete windows, excluding a partial trailing window."""
    _require_aware(start, "start")
    _require_aware(watermark, "watermark")
    if watermark < start:
        raise ValueError("watermark must not precede start")

    windows: list[LogicalWindow] = []
    cursor = start
    while cursor + WINDOW_DURATION <= watermark:
        window = LogicalWindow.starting_at(cursor)
        windows.append(window)
        cursor = window.end
    return tuple(windows)
