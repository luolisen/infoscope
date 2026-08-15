from collections.abc import Awaitable, Callable

from infoscope.db import ping_database
from infoscope.schemas.health import HealthResponse


class HealthService:
    def __init__(self, database_ping: Callable[[], Awaitable[None]] = ping_database) -> None:
        self._database_ping = database_ping

    async def check(self) -> HealthResponse:
        await self._database_ping()
        return HealthResponse()


def get_health_service() -> HealthService:
    return HealthService()
