# Pre-production security backlog — database roles and identity

Status as of Sprint 4: database roles are now split least-privilege
(bootstrap/migrator/runtime/audit-read-only, each verified), and analyst
identity is backed by a real OIDC provider (Keycloak) instead of
Sprint 3's placeholder shared-secret JWT — see
`docs/sprint-4-identity-and-authz.md` for the full design and what was
and wasn't independently re-verified. Still not production-ready: see
items 1, 5, and 6 below, and the "honest limits" section of that doc.
Do not describe database isolation or analyst authentication as
production-ready until the items below are resolved and re-verified.

## 1. Narrow `n8n_internal`'s database-level grant

**Decision (recorded, not yet acted on): leave as-is for local development.**
n8n is a working installation with 32 live tables; re-narrowing its grant
now risks breaking it for a permissions change that only matters before
real financial data is involved, with no application yet built to protect.
Revisit this deliberately, on its own, before production — not bundled
into unrelated work.

Currently: `GRANT CONNECT, CREATE, TEMPORARY ON DATABASE fincrime TO n8n_internal;`
— database-wide, not scoped to the `n8n` schema it owns.

- Evaluate whether n8n/TypeORM's initialization and migration sequence
  still succeeds with `CREATE`/`TEMPORARY` granted only at the schema level
  (`GRANT CREATE ON SCHEMA n8n TO n8n_internal;`) instead of at the database
  level, now that Postgres 15+ restricts both to the DB owner by default.
  Check the actual requirement against the n8n version pinned in
  `docker-compose.yml` before narrowing anything — don't assume the
  schema-level grant is sufficient without testing it.
- If schema-level grants are insufficient (TypeORM's early connection
  checks may run before a schema is selected), document precisely which
  check requires the database-level grant, so the exception is deliberate
  and recorded rather than inherited by default.
- Test any change against a disposable Postgres container first (not this
  project's volume), the same way `app_runtime` below was validated.
- Re-test against a fresh (empty) volume, not just the already-initialized
  one, since `docker-entrypoint-initdb.d` scripts only run once.

## 2. Replace the `app_rw` superuser arrangement

**Mostly done as of Sprint 4.** `app_runtime` no longer owns anything.
Ownership of schema `app` and all its tables moved to a new role,
`app_migrator`, which Alembic now connects as
(`migrations/env.py` reads `POSTGRES_APP_MIGRATOR_USER/PASSWORD` directly
from the environment, never from the app's own `Settings` class — the
running API process never holds a DDL-capable credential in memory).
`app_runtime` was re-granted DML only (`SELECT, INSERT, UPDATE, DELETE`
plus sequence usage) via `ALTER DEFAULT PRIVILEGES`, so future tables
`app_migrator` creates are usable by the API immediately, without a
separate manual grant step each time.

Validated on a disposable Postgres container first (ownership transfer,
then confirmed: `app_runtime` can still read/write existing data but is
denied `CREATE TABLE`; `app_migrator` can create tables; a table
`app_migrator` creates afterward is immediately writable by
`app_runtime` with no extra grant), then applied identically to the live,
non-recreated Postgres container.

Still open:
- `app_rw` itself is still the Postgres container's `POSTGRES_USER`, and
  the official postgres image always makes that role a superuser
  (`Superuser, Create role, Create DB, Replication, Bypass RLS`). It is
  used only for `infra/docker/postgres-init/*.sh` now (role bootstrap for
  `app_runtime`, `app_migrator`, `app_audit_ro`, `n8n_internal`,
  `keycloak_internal`) — never for serving requests or running
  migrations.
- Decide whether `app_rw` should be replaced by a genuinely non-superuser
  bootstrap arrangement, or kept superuser but confined to image-init only
  (already true in practice, not yet enforced any other way).

## 3. Define and implement `app_audit_ro`

**Done as of Sprint 4.** Role created by
`infra/docker/postgres-init/06-create-app-audit-ro-role.sh`; granted
`SELECT` on exactly `app.audit_events` and `app.case_history` by a real
Alembic migration (`b794c1007fea_grant_app_audit_ro...py`, raw
`op.execute` — those tables don't exist yet at first-init time on a
fresh volume, so the grant has to happen after migrations create them,
not in the init script). Verified directly: can read both tables, denied
on every other table (including `organizations`), denied on every write
— including `INSERT` into `audit_events` itself.

No consumer uses this role yet (no reporting tool/admin view exists) and
no row-level security for tenant scoping was added — it currently sees
all organizations' audit data. Add RLS before handing this role to
anything less trusted than an internal admin.

## 4. Verify role ownership, schema grants, migrations, and clean-state startup

Done against the live, never-recreated Postgres container, for the
current role arrangement (`\du+`, `\dn+`, `pg_tables` ownership checks):
as of Sprint 4, schema `app` has 12 tables, all owned by `app_migrator`;
`app_runtime` has DML-only access to all of them (confirmed: denied
`CREATE TABLE`); `app_audit_ro` reads exactly 2 of them; `n8n` still has
exactly 32 tables, untouched; `public` still has 0.

Still open:
- **Fresh-volume verification was not redone this sprint.** Sprint 1
  verified a fresh-volume cycle for the original `app_runtime`-owns-schema
  arrangement; Sprint 4's role split (`app_migrator` owning the schema
  instead, plus `app_audit_ro`) was validated on a disposable container
  with a *hand-built* replica schema, not by running
  `docker compose down -v` + up from empty against the real init-script
  sequence end-to-end. The init scripts were written to be consistent
  with what was verified live, but that specific combination
  (02 → 05 → 06, then 5 Alembic migrations) has not been exercised from a
  genuinely empty volume. Do this before relying on it for a new
  environment.
- Item 1 (`n8n_internal`'s grant) remains an open decision, unchanged.
- Item 2's `app_rw` superuser question remains open.

## 5. Replace the n8n service token with a real service-account OIDC client

The n8n → API service token (`N8N_API_SERVICE_TOKEN`) is unchanged since
Sprint 1: a static shared secret, not an OIDC client, not subject to
expiry or rotation. Sprint 4 narrowed its blast radius (it can now only
call `POST /api/v1/cases` — case creation on a qualifying alert; every
other case endpoint explicitly rejects it, verified by
`test_service_token_cannot_assign_cases`), but didn't replace the
mechanism itself.

- Add a confidential OIDC client for n8n in `infra/keycloak/realm-export.json`
  with `serviceAccountsEnabled: true` (client-credentials grant), and
  switch the workflow's HTTP Header Auth credential accordingly.
- Decide token lifespan/rotation for that client separately from
  analyst-facing tokens.

## 6. Harden the analyst-identity layer now that it's real (follow-ups from Sprint 4)

Sprint 4 replaced the placeholder HS256 JWT with real Keycloak-issued,
JWKS-validated tokens, and replaced unvalidated org/role claims with a
real `organization_memberships` table (see
`docs/sprint-4-identity-and-authz.md` for the full design). What's
still open on top of that real foundation:

- No token revocation ahead of natural expiry (access tokens are
  short-lived -- 5 minutes -- as the only mitigation; Keycloak's
  introspection endpoint would give instant revocation but costs a
  network round-trip per request and wasn't implemented).
- No refresh-token handling, logout flow, or session UI -- this sprint
  only implemented the resource-server (API-side) validation path.
- "lead" vs "analyst" is still two compared string values in application
  code (`app/services/cases.py`), now backed by a real roster
  (`organization_memberships.role`) instead of a bare claim, but not a
  general RBAC/permissions framework.
- No row-level security anywhere -- tenant isolation is enforced entirely
  in application code (`organization_id` checks on every query), not at
  the database layer.

## Current state summary

- `n8n_internal`: database-wide `CONNECT, CREATE, TEMPORARY` grant, owns
  schema `n8n`. Unchanged by decision (item 1).
- `app_migrator` (new, Sprint 4): owns schema `app` and all its tables.
  Alembic connects as this role; `services/api` never does.
- `app_runtime`: DML-only as of Sprint 4 (no longer owns anything),
  `CONNECT` on the database, no DDL rights. Used by `services/api` for
  all runtime queries.
- `app_rw`: still the bootstrap role, still a Postgres superuser, now
  used only for init scripts.
- `app_audit_ro` (new, Sprint 4): read-only, `audit_events` +
  `case_history` only.
- `keycloak_internal` (new, Sprint 4): owns schema `keycloak` on the same
  Postgres container, mirroring the `n8n_internal`/`n8n` pattern.
- Analyst identity (Sprint 3 → Sprint 4): real Keycloak-issued,
  JWKS-validated OIDC tokens; organization/role no longer in the token at
  all, looked up from `organization_memberships` instead. Item 6 above
  tracks what's still open on top of this.
- n8n service identity: still a static shared token (item 5, open), now
  scoped to case-creation only.
