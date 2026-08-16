#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE="$ROOT/.state/demo"
UV_CACHE_DIR=${UV_CACHE_DIR:-"$ROOT/.state/uv-cache"}
API_PORT=${INFOSCOPE_API_PORT:-8000}
export UV_CACHE_DIR

require() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  }
}

alive() {
  [ -f "$1" ] && kill -0 "$(sed -n '1p' "$1")" 2>/dev/null
}

process_matches() {
  pidfile="$1"
  expected="$2"
  alive "$pidfile" || return 1
  pid=$(sed -n '1p' "$pidfile")
  command=$(ps -p "$pid" -o command= 2>/dev/null || true)
  case "$command" in
    *"$expected"*) return 0 ;;
    *) return 1 ;;
  esac
}

preflight() {
  require docker
  require uv
  require pnpm
  require curl
  docker info >/dev/null 2>&1 || {
    printf 'Docker daemon is not running. Start Docker Desktop or Docker Engine.\n' >&2
    exit 1
  }
  [ -f "$ROOT/.env" ] || {
    printf 'Missing .env. Copy .env.example to .env and add local credentials.\n' >&2
    exit 1
  }
  printf 'Preflight passed.\n'
}

prepare() {
  preflight
  mkdir -p "$STATE" "$UV_CACHE_DIR"
  chmod 700 "$ROOT/.state" "$STATE"
  cd "$ROOT"
  docker compose up -d postgres
  uv sync --project backend --all-groups --locked
  uv run --project backend --no-sync alembic -c backend/alembic.ini upgrade head
  pnpm install --frozen-lockfile
  pnpm build
}

start() {
  prepare
  if alive "$STATE/api.pid" || alive "$STATE/worker.pid"; then
    printf 'Infoscope is already running; use %s status or stop.\n' "$0" >&2
    exit 1
  fi
  cd "$ROOT"
  nohup env PATH="$HOME/.local/bin:$PATH" uv run --project backend --no-sync uvicorn \
    infoscope.api.app:app --host 127.0.0.1 --port "$API_PORT" \
    </dev/null >"$STATE/api.log" 2>&1 &
  printf '%s\n' "$!" >"$STATE/api.pid"
  nohup env PATH="$HOME/.local/bin:$PATH" uv run --project backend --no-sync python -m infoscope.worker \
    --process-ask-queue --process-maintenance-queue \
    --process-personalization-queue --process-brief-queue \
    </dev/null >"$STATE/worker.log" 2>&1 &
  printf '%s\n' "$!" >"$STATE/worker.pid"
  attempts=0
  until curl -fsS "http://127.0.0.1:$API_PORT/api/v1/health" >/dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 30 ] || ! alive "$STATE/api.pid"; then
      printf 'API failed to start. See %s/api.log\n' "$STATE" >&2
      stop
      exit 1
    fi
    sleep 1
  done
  if ! process_matches "$STATE/worker.pid" "python -m infoscope.worker"; then
    printf 'Worker failed to stay running. See %s/worker.log\n' "$STATE" >&2
    stop
    exit 1
  fi
  printf 'Infoscope is ready at http://127.0.0.1:%s\n' "$API_PORT"
}

stop() {
  for name in worker api; do
    pidfile="$STATE/$name.pid"
    expected="uvicorn infoscope.api.app:app"
    [ "$name" = worker ] && expected="python -m infoscope.worker"
    if process_matches "$pidfile" "$expected"; then
      kill "$(sed -n '1p' "$pidfile")"
    fi
    rm -f "$pidfile"
  done
  printf 'Infoscope processes stopped. PostgreSQL remains running.\n'
}

status() {
  for name in api worker; do
    if alive "$STATE/$name.pid"; then
      printf '%s: running\n' "$name"
    else
      printf '%s: stopped\n' "$name"
    fi
  done
}

case "${1:-start}" in
  preflight) preflight ;;
  prepare) prepare ;;
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) printf 'Usage: %s {preflight|prepare|start|stop|restart|status}\n' "$0" >&2; exit 2 ;;
esac
