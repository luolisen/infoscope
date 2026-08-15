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

Checks:

```bash
uv run --project backend ruff check backend/src backend/tests scripts
uv run --project backend pytest backend
uv run --project backend python scripts/generate_openapi.py --check
```
