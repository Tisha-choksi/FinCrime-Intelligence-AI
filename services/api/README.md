# services/api — FastAPI control plane

```
app/
├── main.py              # FastAPI app, router wiring
├── core/
│   ├── config.py        # env-driven settings
│   ├── db.py            # async engine/session (connects as app_runtime)
│   ├── correlation.py   # X-Correlation-Id propagation, shared by routers
│   └── security.py      # service-token + real Keycloak OIDC analyst auth
├── api/v1/
│   ├── health.py        # GET /api/v1/health
│   ├── transactions.py  # POST /api/v1/transactions/import
│   └── cases.py         # CAS-061..065 investigation case management
├── models/               # SQLAlchemy ORM, schema "app"
├── schemas/              # Pydantic request/response models
├── repositories/         # DB access, one per aggregate
└── services/             # ingestion, MON-011 monitoring, audit, cases
migrations/                # Alembic, schema-scoped to "app", runs as app_migrator
tests/
```

## Database roles (Sprint 4 split)

This service connects as **`app_runtime`**, a non-superuser Postgres role
with DML only (`SELECT, INSERT, UPDATE, DELETE`) on schema `app` — it
cannot create or alter tables, cannot touch `public` or n8n's `n8n`
schema. DDL (migrations) runs as a *different* role, **`app_migrator`**,
which owns schema `app`; `services/api`'s own process never holds that
credential. A third role, **`app_audit_ro`**, has read-only access to
exactly `audit_events` and `case_history`, for future reporting/audit
tooling. None of these are superusers — that's still `app_rw`, used only
for bootstrap/init scripts. See
[`docs/pre-production-security-todo.md`](../../docs/pre-production-security-todo.md)
for what's still open (item 1, n8n's grant; item 6, RBAC/RLS).

## Identity (Sprint 4: real OIDC via Keycloak)

Analyst requests carry a real Keycloak-issued access token (RS256,
validated via JWKS — signature/issuer/audience/expiry all checked, see
`app/core/security.py::decode_oidc_token`) plus an `X-Organization-Id`
header asserting which organization the caller is acting in. That
assertion is checked against a real `organization_memberships` row
before being trusted — Keycloak itself carries no organization or role
claims at all, by design (see
[`docs/sprint-4-identity-and-authz.md`](../../docs/sprint-4-identity-and-authz.md)).
The n8n service token is unchanged (a static shared secret) but now
scoped to case-creation only — every other case endpoint rejects it.

## Run via Docker Compose

From the repo root:

```sh
docker compose up -d --build api
curl http://localhost:${API_HOST_PORT:-8000}/api/v1/health
```

(Note: this session built/ran `api` and `keycloak` via plain `docker build`
+ `docker run` on the project's existing network, not `docker compose up`,
because the auto-mode classifier declined a compose-wide reconciliation
pass while the Postgres-recreation-forbidding rule was in effect. A plain
`docker compose up -d --build api` should work normally outside that
constraint.)

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
export OIDC_ISSUER_URL=http://keycloak:8080/realms/fincrime
export OIDC_CLIENT_ID=fincrime-api
# JWKS fetch needs a host-reachable address, unlike the issuer string above
# (see docs/sprint-4-identity-and-authz.md's "issuer vs JWKS address" bug):
export OIDC_JWKS_URL=http://localhost:58080/realms/fincrime/protocol/openid-connect/certs

uvicorn app.main:app --reload --port 8000
```

## Migrations

```sh
# .env must have POSTGRES_APP_MIGRATOR_USER/PASSWORD set (see .env.example)
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

`migrations/env.py` connects as `app_migrator` (never `app_runtime`) and
scopes autogenerate/reflection to the `app` schema only (`include_name`)
— `app_migrator` can't read other schemas (e.g. n8n's or Keycloak's), and
even if it could, this service must never create or alter anything
outside `app`.

## Tests

```sh
pytest
```

~45 tests, real integration tests against local Postgres (`app_runtime`)
and local Keycloak (`tests/conftest.py::analyst_client_factory` creates a
real, disposable Keycloak user per call via the Admin API and deletes it
afterward — not mocked). Covers transaction import, `MON-011` alerting,
full case lifecycle (create/assign/status/link/evidence/history),
cross-organization isolation, invalid/expired/forged tokens (the expired
case waits for a *real* 2-second-lifespan token to actually expire),
invalid analyst assignment, authorization-failure auditing, evidence
tamper detection, and atomic rollback + safe retry on mid-transaction
failures. Skipped automatically if Postgres or Keycloak aren't reachable.

## n8n integration

`n8n/workflows/core/transaction-ingestion-to-api.json` calls
`POST /api/v1/transactions/import` with retries, correlation-ID
propagation, and distinct success/validation/auth/transient-error paths,
and automatically calls `POST /api/v1/cases` when a qualifying alert is
produced. See
[`docs/sprint-2-n8n-workflow-integration.md`](../../docs/sprint-2-n8n-workflow-integration.md),
[`docs/sprint-3-case-management.md`](../../docs/sprint-3-case-management.md),
and
[`docs/sprint-4-identity-and-authz.md`](../../docs/sprint-4-identity-and-authz.md).

## Known gaps (tracked, not fixed here)

`app_rw` is still a Postgres superuser (bootstrap-only use), the n8n
service token is still a static shared secret (not a real OIDC
service-account client), there's no token revocation ahead of natural
expiry, no RBAC framework (just two compared role strings), and no
row-level security anywhere (tenant isolation is entirely
application-code-enforced). See
[`docs/pre-production-security-todo.md`](../../docs/pre-production-security-todo.md).
Do not describe this service as production-ready — locally verified and
production-ready are not the same claim.
