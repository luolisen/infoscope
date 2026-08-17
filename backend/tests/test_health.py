from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from infoscope.api.app import app
from infoscope.schemas.health import HealthResponse
from infoscope.services.health import HealthService, get_health_service


class HealthyService(HealthService):
    async def check(self) -> HealthResponse:
        return HealthResponse()


class UnhealthyService(HealthService):
    async def check(self) -> HealthResponse:
        raise RuntimeError("database unavailable")


async def test_health_service_reports_worker_unavailable_without_failing_api() -> None:
    service = HealthService(database_ping=AsyncMock(), worker_check=AsyncMock(return_value=False))

    response = await service.check()

    assert response == HealthResponse(status="degraded", worker="unavailable")


async def test_health_service_reports_worker_ready() -> None:
    service = HealthService(database_ping=AsyncMock(), worker_check=AsyncMock(return_value=True))

    response = await service.check()

    assert response == HealthResponse()


async def test_health_contract() -> None:
    app.dependency_overrides[get_health_service] = HealthyService
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "api": "ok",
        "database": "ok",
        "worker": "ok",
    }
    assert response.headers["x-request-id"]


async def test_health_failure_uses_error_contract() -> None:
    app.dependency_overrides[get_health_service] = UnhealthyService
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/health", headers={"x-request-id": "test-request-id"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred.",
            "request_id": "test-request-id",
        }
    }
    assert response.headers["x-request-id"] == "test-request-id"
