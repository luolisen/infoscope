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

process_started_at() {
  ps -p "$1" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

write_pidfile() {
  pidfile="$1"
  pid="$2"
  started_at=$(process_started_at "$pid")
  [ -n "$started_at" ] || return 1
  {
    printf '%s\n' "$pid"
    printf '%s\n' "$started_at"
  } >"$pidfile"
}

process_matches() {
  pidfile="$1"
  expected="$2"
  alive "$pidfile" || return 1
  pid=$(sed -n '1p' "$pidfile")
  recorded_started_at=$(sed -n '2p' "$pidfile")
  [ -n "$recorded_started_at" ] || return 1
  current_started_at=$(process_started_at "$pid")
  [ "$recorded_started_at" = "$current_started_at" ] || return 1
  command=$(ps -p "$pid" -o command= 2>/dev/null || true)
  case "$command" in
    *"$expected"*) return 0 ;;
    *) return 1 ;;
  esac
}

port_in_use() {
  command -v python3 >/dev/null 2>&1 || return 1
  python3 -c 'import socket, sys
s = socket.socket()
s.settimeout(0.2)
try:
    occupied = s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
finally:
    s.close()
raise SystemExit(0 if occupied else 1)' "$API_PORT"
}

health_has_worker() {
  curl -fsS "http://127.0.0.1:$API_PORT/api/v1/health" 2>/dev/null \
    | grep -q '"worker":"ok"'
}

preflight() {
  require docker
  require uv
  require pnpm
  require curl
  require python3
  docker info >/dev/null 2>&1 || {
    printf 'Docker daemon is not running. Start Docker Desktop or Docker Engine.\n' >&2
    exit 1
  }
  [ -f "$ROOT/.env" ] || {
    printf 'Missing .env. Copy .env.example to .env and add local credentials.\n' >&2
    exit 1
  }
  if env PATH="$HOME/.local/bin:$PATH" uv run --project "$ROOT/backend" --no-sync \
    python -m infoscope.worker --check-research-capability >/dev/null 2>&1; then
    printf 'Research capability ready.\n'
  else
    printf 'Research capability unavailable; direct Ask remains available.\n' >&2
  fi
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
  if process_matches "$STATE/api.pid" "uvicorn infoscope.api.app:app" \
    || process_matches "$STATE/worker.pid" "python -m infoscope.worker"; then
    printf 'Infoscope is already running; use %s status or stop.\n' "$0" >&2
    exit 1
  fi
  for pidfile in "$STATE/api.pid" "$STATE/worker.pid"; do
    if [ -f "$pidfile" ]; then
      printf 'Removing stale PID file: %s\n' "$pidfile" >&2
      rm -f "$pidfile"
    fi
  done
  if port_in_use; then
    printf 'Port %s is occupied by an unmanaged process; refusing to start.\n' "$API_PORT" >&2
    exit 1
  fi
  cd "$ROOT"
  nohup env PATH="$HOME/.local/bin:$PATH" uv run --project backend --no-sync uvicorn \
    infoscope.api.app:app --host 127.0.0.1 --port "$API_PORT" \
    </dev/null >"$STATE/api.log" 2>&1 &
  api_pid="$!"
  write_pidfile "$STATE/api.pid" "$api_pid" || {
    printf 'API process exited before its identity could be recorded. See %s/api.log\n' "$STATE" >&2
    exit 1
  }
  nohup env PATH="$HOME/.local/bin:$PATH" uv run --project backend --no-sync python -m infoscope.worker \
    --process-ask-queue --process-maintenance-queue \
    --process-personalization-queue --process-brief-queue \
    --process-event-localization-queue \
    </dev/null >"$STATE/worker.log" 2>&1 &
  worker_pid="$!"
  write_pidfile "$STATE/worker.pid" "$worker_pid" || {
    printf 'Worker exited before its identity could be recorded. See %s/worker.log\n' "$STATE" >&2
    stop
    exit 1
  }
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
  process_matches "$STATE/api.pid" "uvicorn infoscope.api.app:app" || {
    printf 'Health response did not come from this Demo API process. See %s/api.log\n' "$STATE" >&2
    stop
    exit 1
  }
  attempts=0
  until health_has_worker; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 30 ] \
      || ! process_matches "$STATE/worker.pid" "python -m infoscope.worker"; then
      printf 'Worker failed readiness. See %s/worker.log\n' "$STATE" >&2
      stop
      exit 1
    fi
    sleep 1
  done
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
  if process_matches "$STATE/api.pid" "uvicorn infoscope.api.app:app"; then
    printf 'api: running\n'
  elif [ -f "$STATE/api.pid" ]; then
    if port_in_use; then
      printf 'api: stale PID file; unmanaged process on port %s\n' "$API_PORT"
    else
      printf 'api: stale PID file\n'
    fi
  elif port_in_use; then
    printf 'api: unmanaged process on port %s\n' "$API_PORT"
  else
    printf 'api: stopped\n'
  fi
  if process_matches "$STATE/worker.pid" "python -m infoscope.worker"; then
    printf 'worker: running\n'
  elif [ -f "$STATE/worker.pid" ]; then
    printf 'worker: stale PID file\n'
  else
    printf 'worker: stopped\n'
  fi
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
