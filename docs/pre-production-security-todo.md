# Pre-production security backlog — database roles

Status as of the current local setup: functional and schema-isolated
(verified — see `docs/local-n8n-setup.md`), but **not** least-privilege.
Do not describe database isolation as production-ready until the items
below are resolved and re-verified.

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

**Partially done.** `services/api` now connects as a new, separate
non-superuser role, `app_runtime` — created by
`infra/docker/postgres-init/02-create-app-runtime-role.sh`, owning only its
own `app` schema (mirrors the `n8n_internal`/`n8n` pattern). Verified on a
disposable Postgres container first, then applied to the live volume via
the same manual-grant approach used for the earlier n8n fix (no volume
recreation): `app_runtime` can create/manage objects in `app`, and is
denied on `public` and on creating new schemas — confirmed by direct test
(`CREATE TABLE public.leak_test` → `permission denied`). Alembic migrations
run as `app_runtime` too, scoped to the `app` schema only
(`migrations/env.py`'s `include_name` filter — `app_runtime` can't even
read other schemas, e.g. `n8n`, so unscoped autogenerate would error).

Still open:
- `app_rw` itself is still the Postgres container's `POSTGRES_USER`, and
  the official postgres image always makes that role a superuser
  (`Superuser, Create role, Create DB, Replication, Bypass RLS`). It is no
  longer used by the running API, but it's still the bootstrap/init-script
  role and the role used to run `infra/docker/postgres-init/*.sh`.
- No separate **migration** role exists yet, distinct from both the
  bootstrap role and the application runtime role. Right now
  `app_runtime` runs its own migrations because it owns its schema — this
  works for a single-service schema-per-owner model, but doesn't yet match
  the "dedicated migration role" shape called for before production.
  Revisit once there's a concrete reason to split them (e.g. the runtime
  role should not have DDL rights at all in a hardened deployment).
- Decide whether `app_rw` should be replaced by a genuinely non-superuser
  bootstrap arrangement, or kept superuser but used *only* for
  image-init/migration tasks and never for serving requests (already true
  today, since `services/api` uses `app_runtime`).

## 3. Define and implement `app_audit_ro`

Referenced in `plan.md` §3 ("Sprint 1") as a least-privilege role but not
yet created.

- Define its intended scope: read-only access to `audit_events` (and
  likely other append-only/audit tables as they're added), no write
  privileges at all, enforced at the Postgres grant level rather than only
  the application layer.
- Decide which consumers use it (reporting, external audit tooling, an
  internal admin view) before implementing — this determines whether it
  also needs row-level security for tenant (`organization_id`) scoping.

## 4. Verify role ownership, schema grants, migrations, and clean-state startup

Done for `app_runtime` specifically (`\du+`, `\dn+`, `pg_tables` ownership
checks against the live `fincrime` database — see `services/api/README.md`
and this session's verification: 6 tables in `app`, all owned by
`app_runtime`; 32 tables in `n8n` and 0 in `public`, untouched).

Still open, once items 1 and 2's remaining parts land:

- Re-run the same checks against whatever bootstrap/migration-role split
  comes out of item 2.
- Confirm a full `docker compose down -v` + `docker compose up` cycle
  succeeds from an empty volume — `01-create-n8n-role.sh` and
  `02-create-app-runtime-role.sh` have only ever run once (at original
  volume init) plus been manually re-applied to the live volume; neither
  has been exercised against a genuinely fresh one yet.
- Confirm `services/api`'s `/api/v1/health` and n8n's own startup both
  still succeed end-to-end under whatever the final role arrangement is.

## Current state summary

- `n8n_internal`: database-wide `CONNECT, CREATE, TEMPORARY` grant, owns
  schema `n8n`. Unchanged by decision (item 1).
- `app_runtime` (new this session): owns schema `app` only, `CONNECT` on
  the database, no database-level `CREATE`/`TEMPORARY`, no superuser
  attributes. Used by `services/api` for both runtime queries and
  migrations.
- `app_rw`: still the bootstrap role, still a Postgres superuser. No
  longer used by `services/api`. Item 2's remaining parts (migration-role
  split, decide `app_rw`'s long-term shape) are open.
- `app_audit_ro`: not created (item 3, open).
