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

Phase 3 Window Analysis consumes consecutive one-hour acquisition windows using
`Raw.acquired_at` and left-closed/right-open `[start, end)` boundaries. The
first window begins at the earliest Raw; only complete windows whose end is at
or before the current watermark are eligible. Configure the OpenAI-compatible
DeepSeek endpoint locally (never commit real keys):

```dotenv
ANALYSIS_API_BASE_URL=https://api.deepseek.com
ANALYSIS_MODEL=deepseek-v4-pro
ANALYSIS_API_KEYS=sk-first,sk-second,sk-third
```

```bash
uv run --project backend alembic upgrade head
uv run --project backend python -m infoscope.worker --analyze-windows
uv run --project backend python -m infoscope.worker --retry-window-run RUN_ID
uv run --project backend python -m infoscope.worker --replay-window-run RUN_ID
```

The model receives normalized Signals only. Private Telegram provenance must
already be absent and is rejected if it reaches this boundary. Validated JSON
is persisted as an internal `window_analysis.v1` artifact before the pipeline
checkpoint advances; it does not create Events, Signals, NOW data, or a Public
API. API, schema, coverage, and prerequisite failures stop later windows and do
not advance the checkpoint. Multiple local keys rotate across retries without
being logged. `WINDOW_ANALYSIS_MAX_SIGNALS` and
`WINDOW_ANALYSIS_MAX_INPUT_CHARS` reject oversized windows before any model
request; splitting a logical window requires a separately frozen aggregation
contract and is not performed implicitly.

Normal window execution reuses the newest failed run for the same window once
its `next_retry_at` is due, incrementing `attempt` without recollecting Raw.
Operators may retry a failed run immediately or replay any terminal run by UUID.
Audit logs contain only pipeline/run identifiers, window boundaries, attempt,
counts, status, stable error code, and retry time; Signal text and provenance
are never logged.

Phase 4 Event Reconstruction consumes one successful `window_analysis.v1`
artifact by opaque UUID:

```bash
uv run --project backend alembic upgrade head
uv run --project backend python -m infoscope.worker \
  --reconstruct-window-artifact ARTIFACT_ID
```

The strict `event_reconstruction.v1` output may propose new Events, update only
Backend-supplied candidate Event IDs, or leave Signals unassigned. The model
never creates Event IDs. The Backend validates complete one-time Signal
coverage, assigns IDs, and atomically persists the reconstruction artifact,
Events, and Event–Signal links before completing the pipeline run. Reprocessing
the same source artifact locks and reuses its canonical artifact without another
model call. A database source key prevents concurrent duplicate persistence.
Model state values are non-authoritative suggestions: new Events start as
`developing`, while existing Events retain their valid state until deterministic
Claim / Conflict rules are available. This slice does not create Claims,
Timeline, Conflicts, personalization, Public API fields, or frontend behavior.

Claim Extraction and Timeline Reconstruction consume canonical upstream
artifacts by UUID:

```bash
uv run --project backend python -m infoscope.worker --extract-claims-artifact ARTIFACT_ID
uv run --project backend python -m infoscope.worker --reconstruct-timeline-artifact ARTIFACT_ID
uv run --project backend python -m infoscope.worker --analyze-conflicts-artifact ARTIFACT_ID
uv run --project backend python -m infoscope.worker --analyze-base-artifact ARTIFACT_ID
```

Claims start deterministically as `unresolved`; the model cannot write Claim
state. Timeline input includes the corresponding Event, Claims, and sanitized
Evidence Signal text, timestamps, and public-safe provenance. Claim–Signal and
Timeline–Claim links are many-to-many and may reference only entities supplied
by the Backend for the same Event. Both pipelines lock
their source artifact before the model call, reuse canonical outputs, validate
complete used/unused coverage, and atomically persist entities, links, and the
internal artifact. No Public API or frontend contract is added in this slice.

Conflict Analysis consumes a canonical `timeline_reconstruction.v1` artifact. Its model input
contains current Claims and only their attached sanitized Evidence text, nullable `published_at`,
and public-safe provenance. The Backend validates Event/Claim/Evidence scope and full Claim
coverage; semantic contradiction remains the model's constrained judgment. Existing Conflict
updates append relations without removing history, while `unconflicted_claim_ids` means only that
the current run made no Conflict decision for those Claims. Conflict persistence deterministically
moves unresolved or confirmed Claims and their Event to `conflicting`, preserves contradicted
Claims, and atomically stores the internal artifact. No Public API or frontend contract is added.

Base Analysis consumes canonical `conflict_analysis.v1` artifacts. Its Event scope combines
Conflict decision Event IDs with Event IDs resolved from every unconflicted Claim, so an all-
unconflicted result is not lost. An empty scope writes a canonical no-op artifact without calling
the model. Each Event receives one user-independent current snapshot containing summary, event
type, categorical importance, topics, and Event-local entities. Existing snapshots are fully
replaced while immutable pipeline artifacts retain history. The model cannot change Event or Claim
state or promote unstructured Evidence into new facts. No Public API or frontend contract is added.

Research Integration v1 uses OpenClaw for headless public-source discovery and Agent-Reach only
as the installed capability/health layer. The model returns URLs, never Evidence text. The backend
validates each URL against the frozen HTTPS/SSRF policy, fetches the real public document, and
persists it as `source_type=research` Raw before normal normalization and deduplication.
The immutable discovery artifact keeps every candidate in order: accepted candidates retain the
source kind, canonical URL, URL hash, and model relevance summary; rejected candidates retain only
the source kind, URL hash, and stable error code, so credential-bearing raw URLs are never stored.

Install and configure the pinned external runtime separately, then verify it locally:

```bash
npm install --global openclaw@2026.7.1-2
agent-reach doctor
openclaw --version
openclaw agent --help
```

Provision a dedicated regular OpenClaw config containing the `infoscope-research` agent, its
workspace, and least-privilege tool policy. Configure its path, isolated state directory, and model
reference in `.env`. Export `DEEPSEEK_API_KEY` in the worker process environment; it is the only
model credential variable admitted by the fixed subprocess allowlist. The adapter inherits only
`PATH`; it fixes `HOME` and `TMPDIR` to 0700 directories below the dedicated Research state and
injects `OPENCLAW_CONFIG_PATH` and `OPENCLAW_STATE_DIR`. Agent-Reach doctor uses the same isolated
HOME and TMPDIR. No other inherited environment variables reach either subprocess. Never commit
the credential or runtime state.

The adapter invokes `openclaw agent --local --agent infoscope-research --session-key
research-<request_id>` with a 0600 UTF-8 prompt file inside a per-run 0700 work directory. The
request-scoped session key prevents context from being shared between Research requests. It never
uses the Gateway, stdin, delivery, a channel, or a recipient. The prompt and per-run work directory
are cleaned on every outcome. Run an internal request from a local JSON file:

```bash
uv run --project backend alembic upgrade head
uv run --project backend python -m infoscope.worker \
  --research-request-file /absolute/path/to/request.json
uv run --project backend python -m infoscope.worker \
  --retry-research-request REQUEST_ID
```

The request file contains only the internal trigger and selection input; the backend reads and
validates the complete fact snapshot from PostgreSQL:

```json
{
  "idempotency_key": "00000000-0000-4000-8000-000000000001",
  "trigger": "ask_missing_fact",
  "source_event_ids": ["00000000-0000-4000-8000-000000000002"],
  "research_questions": ["What verified public update is missing?"],
  "missing_fact_descriptions": [],
  "allowed_source_kinds": ["web_page", "github_document"]
}
```

The v1 fetcher never follows redirects or uses cookies, authorization headers, proxy environment,
IP-literal hosts, private addresses, or authenticated sources. HTML extraction is locked to
Beautiful Soup 4.15.0 with Python's `html.parser`. A Research result never directly changes Event,
Claim, Timeline, Conflict, Base Analysis, NOW, or any Public API contract.

After an internal Ask Database Comparison returns `research_required`, run its frozen Research
Bridge explicitly with the Ask ID:

```bash
uv run --project backend python -m infoscope.worker \
  --run-ask-research-bridge ASK_ID
```

The Bridge reuses exactly one idempotent Research request, normalizes only that request's
successful Raw records into Signals, and stops at `pending / awaiting_reconciliation`. It does not
run Event Reconciliation, generate the final answer, or expose a Public API.

After the Bridge succeeds, reconcile only its researched Signals into the selected Events:

```bash
uv run --project backend python -m infoscope.worker \
  --run-ask-event-reconciliation ASK_ID
```

This performs targeted exact deduplication, sends a strict current Event snapshot plus canonical
Signals to the Analysis adapter, then locks and rebuilds the full input before commit. It only
appends EventSignal relations, preserves Event state, and stops at `pending / finalizing`; it does
not generate the final Ask answer or expose a Public API.

Checks:

```bash
uv run --project backend ruff check backend/src backend/tests scripts
uv run --project backend pytest backend
uv run --project backend python scripts/generate_openapi.py --check
```
