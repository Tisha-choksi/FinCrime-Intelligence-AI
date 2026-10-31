# services/api — FastAPI control plane

```
app/
├── main.py              # FastAPI app, router wiring
├── core/
│   ├── config.py        # env-driven settings
│   ├── db.py            # async engine/session (connects as app_runtime)
│   ├── correlation.py   # X-Correlation-Id propagation, shared by routers
│   └── security.py      # placeholder service-token + analyst-JWT auth (not OIDC yet)
├── api/v1/
│   ├── health.py        # GET /api/v1/health
│   ├── transactions.py  # POST /api/v1/transactions/import
│   └── cases.py         # CAS-061..065 investigation case management
├── models/               # SQLAlchemy ORM, schema "app"
├── schemas/              # Pydantic request/response models
├── repositories/         # DB access, one per aggregate
└── services/             # ingestion, MON-011 monitoring, audit
migrations/                # Alembic, schema-scoped to "app"
tests/
```

## Database role

This service connects as **`app_runtime`**, a non-superuser Postgres role
that owns exactly one schema (`app`) and nothing else — it cannot read or
write `public` or n8n's `n8n` schema, and cannot create new schemas. It is
*not* the bootstrap role (`app_rw`, still a superuser for now — see
[`docs/pre-production-security-todo.md`](../../docs/pre-production-security-todo.md)
for the remaining role-hardening backlog). Migrations run as `app_runtime`
too, since it owns the schema it's migrating.

## Run via Docker Compose

From the repo root:

```sh
docker compose up -d --build api
curl http://localhost:${API_HOST_PORT:-8000}/api/v1/health
```

## Run locally without Docker

```sh
cd services/api
python -m venv .venv
. .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt

export PYTHONPATH="$PWD"
export POSTGRES_HOST=localhost POSTGRES_PORT=55432
export POSTGRES_APP_RUNTIME_PASSWORD=<value from ../../.env>
export N8N_API_SERVICE_TOKEN=<value from ../../.env>
export API_JWT_SECRET=<value from ../../.env>

uvicorn app.main:app --reload --port 8000
```

## Migrations

```sh
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

`migrations/env.py` scopes autogenerate/reflection to the `app` schema only
(`include_name`) — `app_runtime` cannot read other schemas, and even if it
could, this service must never create or alter anything outside `app`.

## Tests

```sh
pytest
```

`test_health.py` is a pure unit test (fake DB dependency, no Postgres
needed). `test_transactions.py` and `test_cases.py` are real integration
tests against the local Postgres (via `app_runtime`) covering valid
import, alert creation (`MON-011`), case creation/assignment/status
transitions, duplicate idempotency, input validation, cross-organization
isolation, unauthorized assignment, missing/wrong auth, and atomic
rollback + safe retry on mid-transaction failures. These are skipped
automatically if no local Postgres is reachable.

## n8n integration

`n8n/workflows/core/transaction-ingestion-to-api.json` calls
`POST /api/v1/transactions/import` with retries, correlation-ID
propagation, and distinct success/validation/auth/transient-error paths,
and (Sprint 3) automatically calls `POST /api/v1/cases` when a qualifying
alert is produced. See
[`docs/sprint-2-n8n-workflow-integration.md`](../../docs/sprint-2-n8n-workflow-integration.md)
and
[`docs/sprint-3-case-management.md`](../../docs/sprint-3-case-management.md).

## Known gaps (tracked, not fixed here)

`app_rw` (used only for bootstrap/migrations of other roles, not by this
service) is still a Postgres superuser, there's no separate migration role
distinct from it yet, `app_audit_ro` doesn't exist yet, and (Sprint 3) the
analyst-JWT auth layer has no real identity provider, user directory, or
revocation behind it. See
[`docs/pre-production-security-todo.md`](../../docs/pre-production-security-todo.md).
Do not describe this service as having production-ready database
isolation or authentication until that backlog is resolved.
