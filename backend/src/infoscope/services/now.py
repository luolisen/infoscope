from datetime import UTC, datetime, timedelta

from infoscope.schemas.now import NowResponse, WindowStats


class NowService:
    def get_now(self, *, limit: int, cursor: str | None) -> NowResponse:
        # Phase 2 intentionally returns an empty collection. Phase 3 will replace
        # these zero counts with persisted Raw/Signal/Event queries without
        # changing this public contract.
        _ = (limit, cursor)
        current_time = datetime.now(UTC)
        window_started_at = current_time.replace(minute=0, second=0, microsecond=0)
        window_ended_at = window_started_at + timedelta(hours=1)
        return NowResponse(
            window_stats=WindowStats(
                window_started_at=window_started_at,
                window_ended_at=window_ended_at,
                raw_information_count=0,
                event_count=0,
                relevant_event_count=0,
            ),
            items=[],
            next_cursor=None,
        )


def get_now_service() -> NowService:
    return NowService()
