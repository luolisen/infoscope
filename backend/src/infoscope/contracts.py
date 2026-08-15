import json
from pathlib import Path

from infoscope.api.app import app


def render_openapi() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_openapi(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_openapi(), encoding="utf-8")
