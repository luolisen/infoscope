from __future__ import annotations

import argparse
from pathlib import Path

from infoscope.contracts import render_openapi, write_openapi

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = ROOT / "contracts" / "openapi.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the committed OpenAPI contract"
    )
    parser.add_argument(
        "--check", action="store_true", help="Fail if the contract is stale"
    )
    args = parser.parse_args()

    rendered = render_openapi()
    if args.check:
        if (
            not OPENAPI_PATH.exists()
            or OPENAPI_PATH.read_text(encoding="utf-8") != rendered
        ):
            raise SystemExit("contracts/openapi.json is stale; regenerate it")
        return 0

    write_openapi(OPENAPI_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
