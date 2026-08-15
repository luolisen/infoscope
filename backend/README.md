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

TG News is a native Telegram user-API adapter. It resolves the dialog filter
whose title exactly matches `TELEGRAM_FOLDER_TITLE` (`News` by default), then
collects text and media captions from the groups and channels in that folder.
It does not use the Bot API, call AI services, expose a public endpoint, or
download media files.

Keep `TELEGRAM_API_HASH` and the generated Telethon session local. Configure
`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and optionally `TELEGRAM_PHONE` in
`.env`, then authorize the user session interactively:

```bash
uv run --project backend python -m infoscope.worker --telegram-login
```

Enter the phone number, Telegram code, and optional 2FA password only in that
local terminal. The generated session is stored below `.state/` by default and
is ignored by Git. Run one collection cycle after authorization:

```bash
uv run --project backend python -m infoscope.worker --collect-telegram
```

The first collection keeps the newest `TELEGRAM_INITIAL_MESSAGE_LIMIT` messages
per dialog (100 by default), persisted oldest-first. Later runs read every
message after that dialog's highest durable message ID. Publicly addressable
groups/channels are `public`; all others are `private`. Direct-user and bot
dialogs are never collected even if they are explicitly present in the folder.

Phase 3 deterministic normalization maps each supported Raw record to one
`signal_index=0` Signal. It performs only Unicode/line-ending cleanup,
source-field mapping, public provenance allowlisting, and content hashing. It
does not summarize, classify, filter, or call an AI service.

```bash
uv run --project backend python -m infoscope.worker --normalize
uv run --project backend python -m infoscope.worker --retry-normalization
```

Each command processes one batch (`NORMALIZATION_BATCH_SIZE`, default 500).
Deterministic record failures are isolated with stable error codes. Private
Telegram provenance is removed by the Signal persistence boundary; identity in
the body is replaced with `[PRIVATE_SOURCE_REDACTED]` before it is stored as
`private_sanitized` evidence.

Phase 3 exact deduplication links Signals whose normalized-text SHA-256 values
are identical. The earliest `(created_at, id)` Signal remains canonical and all
later exact matches point directly to it through `duplicate_of_signal_id`.
Signals and their independent visibility/provenance are retained; this step
does not merge content or reconstruct Events.

```bash
uv run --project backend python -m infoscope.worker --deduplicate
```

The command scans all current canonical candidates in stable batches
(`DEDUPLICATION_BATCH_SIZE`, default 500) and is idempotent. Semantic or fuzzy
deduplication remains frozen until its model, threshold, and output contract are
confirmed.

Checks:

```bash
uv run --project backend ruff check backend/src backend/tests scripts
uv run --project backend pytest backend
uv run --project backend python scripts/generate_openapi.py --check
```
