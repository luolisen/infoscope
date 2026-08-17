from collections.abc import Awaitable, Callable

from infoscope.db import ping_database
from infoscope.schemas.health import HealthResponse
from infoscope.services.worker_health import worker_is_available


class HealthService:
    def __init__(
        self,
        database_ping: Callable[[], Awaitable[None]] = ping_database,
        worker_check: Callable[[], Awaitable[bool]] = worker_is_available,
    ) -> None:
        self._database_ping = database_ping
        self._worker_check = worker_check

    async def check(self) -> HealthResponse:
        await self._database_ping()
        worker_available = await self._worker_check()
        return HealthResponse(
            status="ok" if worker_available else "degraded",
            worker="ok" if worker_available else "unavailable",
        )


def get_health_service() -> HealthService:
    return HealthService()
