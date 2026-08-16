from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from infoscope.api.app import mount_frontend


async def test_built_frontend_serves_index_and_spa_routes(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>Infoscope</h1>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    application = FastAPI()
    assert mount_frontend(application, dist)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        root = await client.get("/")
        spa = await client.get("/events/123")
        asset = await client.get("/assets/app.js")
        missing_api = await client.get("/api/v1/missing")

    assert root.status_code == 200
    assert spa.status_code == 200
    assert "Infoscope" in spa.text
    assert asset.text == "console.log('ok')"
    assert missing_api.status_code == 404


def test_missing_frontend_build_is_a_supported_api_only_mode(tmp_path: Path) -> None:
    assert not mount_frontend(FastAPI(), tmp_path / "missing")
