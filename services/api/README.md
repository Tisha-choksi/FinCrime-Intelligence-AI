# services/api — FastAPI control plane

Skeleton only: config, DB connectivity, health checks, tests. No business
endpoints, no migrations yet — see `plan.md` §2 for what comes next.

## Run via Docker Compose (recommended)

From the repo root:

```sh
docker compose up -d --build api
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

`/health/ready` opens a real connection to Postgres as `app_rw` and runs
`SELECT 1`. It does not depend on any table existing yet.

## Run locally without Docker

```sh
cd services/api
python -m venv .venv
. .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt

# needs POSTGRES_APP_PASSWORD at minimum; the rest default to the
# docker-compose values. If Postgres is reachable at localhost:55432
# (the host-mapped port from .env), override POSTGRES_HOST/POSTGRES_PORT:
export POSTGRES_APP_PASSWORD=<value from ../../.env>
export POSTGRES_HOST=localhost
export POSTGRES_PORT=55432

uvicorn app.main:app --reload --port 8000
```

## Tests

```sh
pytest
```

Tests never touch a real database — `/health/ready`'s DB dependency is
overridden with a fake session, so `pytest` runs with no Postgres required.

## Known gaps (tracked, not fixed here)

The DB role this service connects as (`app_rw`) is currently a Postgres
superuser, and `n8n_internal`'s grant is broader than strictly necessary.
See [`docs/pre-production-security-todo.md`](../../docs/pre-production-security-todo.md).
This service must not be described as having production-ready database
isolation until that backlog is resolved.
