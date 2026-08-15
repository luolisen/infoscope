from pathlib import Path

from infoscope.contracts import render_openapi


def test_committed_openapi_is_current() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    committed = (repository_root / "contracts" / "openapi.json").read_text(encoding="utf-8")
    assert committed == render_openapi()


def test_health_path_is_versioned() -> None:
    assert "/api/v1/health" in render_openapi()
