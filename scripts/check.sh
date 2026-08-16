#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
UV_CACHE_DIR=${UV_CACHE_DIR:-"$ROOT/.state/uv-cache"}
export UV_CACHE_DIR

cd "$ROOT"
uv sync --project backend --all-groups --locked
uv run --project backend --no-sync ruff check backend/src backend/tests scripts
(cd backend && uv run --no-sync python -m pytest -q)
uv run --project backend --no-sync python scripts/generate_openapi.py --check
pnpm lint
pnpm typecheck
pnpm test
pnpm build
