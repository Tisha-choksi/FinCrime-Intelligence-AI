# Local n8n setup (Docker)

Brings up Postgres, Redis and n8n for local development, per `docker-compose.yml`.

## Prerequisites

- Docker Desktop running.
- A port free for Postgres's host mapping. This machine already has a native
  Postgres listening on `5432`, so the compose file maps the container's 5432
  to host port `55432` instead via `POSTGRES_HOST_PORT` (see `.env`).

## First-time setup

```sh
cp .env.example .env
# edit .env: set POSTGRES_APP_PASSWORD, POSTGRES_N8N_PASSWORD, N8N_ENCRYPTION_KEY
# to random values, e.g. `openssl rand -hex 16`
docker compose up -d postgres redis n8n
```

n8n becomes available at http://localhost:5678/.

## What the stack does differently from a bare n8n quickstart

- **Separate Postgres roles for app vs. n8n**, per readme.md §6 ("Critical
  data model rules") and plan.md §2: `app_rw` owns the `fincrime` database;
  a dedicated `n8n_internal` role owns its own `n8n` schema inside the same
  database. The role and schema are created by
  `infra/docker/postgres-init/01-create-n8n-role.sh`, which Postgres runs
  automatically on first init of an empty data volume
  (`docker-entrypoint-initdb.d`).
- **`n8n_internal` is granted `CONNECT, CREATE, TEMPORARY` on the database**,
  not just `CONNECT`. Postgres 15+ restricts `CREATE` (needed to create
  tables/schemas) and `TEMPORARY` (needed for temp tables) to the database
  owner by default — n8n's TypeORM migrations fail with
  `permission denied for database fincrime` without these grants, even
  though the role already owns its own schema. If you ever recreate the
  `n8n_internal` role by hand instead of via a fresh volume, re-run:
  ```sql
  GRANT CONNECT, CREATE, TEMPORARY ON DATABASE fincrime TO n8n_internal;
  ```
- n8n's own tables are confined to the `n8n` schema (`DB_POSTGRESDB_SCHEMA`),
  separate from the application tables that will live in `public` (or their
  own schema) per the data model in readme.md §6.

## Common operations

| Task | Command |
| --- | --- |
| Start | `docker compose up -d postgres redis n8n` |
| Stop (keep data) | `docker compose stop` |
| Stop and remove containers (keep volumes/data) | `docker compose down` |
| Full reset (wipes Postgres + n8n data) | `docker compose down -v` |
| Logs | `docker compose logs -f n8n` |
| Connect to Postgres as app owner | `docker exec -it fincrimeintelligenceai-postgres-1 psql -U app_rw -d fincrime` |

## Troubleshooting

- **`permission denied for database fincrime` in n8n logs**: see the grants
  note above. Only happens if the `n8n_internal` role was created without
  `CREATE`/`TEMPORARY`, e.g. by editing the role manually outside the init
  script.
- **Postgres container fails with a port-bind error**: another Postgres
  instance (or a previous container) already holds the host port. Change
  `POSTGRES_HOST_PORT` in `.env` to a free port; the container-internal port
  stays `5432` so nothing else needs to change.
- **n8n exits immediately after "Last session crashed"**: check
  `docker compose logs n8n` for the underlying DB error rather than retrying
  blindly — n8n crash-loops on DB init failure by design.
