# Infoscope backend

The API and worker are two native processes from the same Python package.
PostgreSQL is the only Phase 1 service that runs in Docker.

In the Phase 1 skeleton, the Health endpoint performs a real PostgreSQL probe.
The `worker` field confirms that the worker component is part of the runnable
backend baseline; persistent worker liveness will be added only after the job
and heartbeat schema is jointly approved.

From the repository root:

```bash
cp .env.example .env
docker compose up -d postgres
uv sync --project backend --all-groups
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --project backend uvicorn infoscope.api.app:app --reload
```

In a second terminal:

```bash
uv run --project backend python -m infoscope.worker
```

Phase 2 authentication uses a server-side session stored in PostgreSQL. The
browser receives only the opaque `is_session` cookie, which is HttpOnly,
SameSite=Lax, and scoped to `/`. Run migrations before testing these endpoints:

```text
GET  /api/v1/session
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/logout
```

Set `SESSION_COOKIE_SECURE=true` outside the localhost HTTP demo when the API is
served over HTTPS.

The next Phase 2 slice persists the frozen SCOPE, investment-market, and FOCUS
selections. It exposes:

```text
GET  /api/v1/onboarding
PUT  /api/v1/onboarding
GET  /api/v1/scope
PUT  /api/v1/scope
```

Completing onboarding changes the Session state to `ready`. Updating SCOPE
records a durable personalization refresh request timestamp; no external model
or AI API is called by this slice.

The final Phase 2 backend slice exposes `GET /api/v1/now`. It requires a valid
session with completed onboarding and returns the frozen NOW response shape. Its
Phase 2 implementation is intentionally empty: current one-hour window counts
are zero, `items` is empty, and `next_cursor` is null until acquisition and Event
reconstruction are implemented in later phases.

Phase 3 adds a native TrendRadar-compatible acquisition adapter. Its frozen
source list lives in `backend/config/trendradar.yaml`; the path can be replaced
with `TRENDRADAR_CONFIG_PATH`. The adapter reads a NewsNow-compatible Hotlist
API plus RSS/Atom/JSON Feed sources and commits each item to `RawInformation`
before any normalization. It does not run TrendRadar AI, notification, MCP,
SQLite, or scheduling code.

Run one collection cycle from the repository root:

```bash
uv run --project backend python -m infoscope.worker --collect-trendradar
```

Source failures are isolated and logged only as stable error codes. A repeated
NewsNow snapshot or RSS GUID/URL is idempotent; a newer Hotlist snapshot is kept
as a new Raw observation so later Signal processing can reconstruct ranking
changes.

Checks:

```bash
uv run --project backend ruff check backend/src backend/tests scripts
uv run --project backend pytest backend
uv run --project backend python scripts/generate_openapi.py --check
```
