# Pre-production security backlog — database roles

Status as of the current local setup: functional and schema-isolated
(verified — see `docs/local-n8n-setup.md`), but **not** least-privilege.
Do not describe database isolation as production-ready until the items
below are resolved and re-verified.

## 1. Narrow `n8n_internal`'s database-level grant

Currently: `GRANT CONNECT, CREATE, TEMPORARY ON DATABASE fincrime TO n8n_internal;`
— database-wide, not scoped to the `n8n` schema it owns.

- Evaluate whether n8n/TypeORM's initialization and migration sequence
  still succeeds with `CREATE`/`TEMPORARY` granted only at the schema level
  (`GRANT CREATE ON SCHEMA n8n TO n8n_internal;`) instead of at the database
  level, now that Postgres 15+ restricts both to the DB owner by default.
- If schema-level grants are insufficient (TypeORM's early connection
  checks may run before a schema is selected), document precisely which
  check requires the database-level grant, so the exception is deliberate
  and recorded rather than inherited by default.
- Re-test against a fresh (empty) volume, not just the already-initialized
  one, since `docker-entrypoint-initdb.d` scripts only run once.

## 2. Replace the `app_rw` superuser arrangement

Currently: `app_rw` is the Postgres container's `POSTGRES_USER`, which the
official postgres image always makes a superuser — `Superuser, Create role,
Create DB, Replication, Bypass RLS`. The application API (`services/api`)
connects as this role.

- Introduce a separate bootstrap/migration role (superuser or
  database-owner-equivalent, used only for `docker-entrypoint-initdb.d` and
  for running migrations) distinct from the role the running application
  uses day to day.
- Make the application's runtime role (`app_rw`, or a renamed equivalent)
  a plain, non-superuser role with exactly the grants `services/api` needs
  on its own schema(s) — no `CREATEDB`, `CREATEROLE`, `REPLICATION`, or
  `BYPASSRLS`.
- Update `infra/docker/postgres-init/`, `docker-compose.yml`, and `.env*`
  to reflect the two-role split; update `docs/local-n8n-setup.md` accordingly.

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

Once items 1–3 land:

- Re-run the same read-only verification steps used to check the current
  setup (`\l+`, `\du+`, `\dn+`, table ownership queries) against the new
  role arrangement.
- Confirm a full `docker compose down -v` + `docker compose up` cycle
  succeeds from an empty volume — the init script and any migrations must
  both work against a genuinely fresh database, not just the
  already-initialized one currently running.
- Confirm `services/api`'s `/health/ready` and n8n's own startup both still
  succeed end-to-end under the new, narrower roles.

None of this has been implemented yet. The current local stack remains on
`app_rw` (superuser) and the database-wide `n8n_internal` grant described
in `docs/local-n8n-setup.md`, unchanged, until this backlog is actioned.
