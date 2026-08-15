from unittest.mock import AsyncMock, patch

from infoscope.worker.main import run


async def test_worker_once_checks_database_and_exits() -> None:
    database_ping = AsyncMock()
    database_close = AsyncMock()

    with (
        patch("infoscope.worker.main.ping_database", database_ping),
        patch("infoscope.worker.main.close_database", database_close),
    ):
        await run(once=True)

    database_ping.assert_awaited_once()
    database_close.assert_awaited_once()
