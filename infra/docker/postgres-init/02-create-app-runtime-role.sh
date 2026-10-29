#!/usr/bin/env bash
# Creates a non-superuser runtime role for services/api, owning its own
# "app" schema -- mirrors the n8n_internal/n8n isolation pattern. The
# bootstrap role (POSTGRES_USER) remains superuser for image init and
# migrations only; the running API must never connect as it.
# Validated against a disposable Postgres container before being added here
# -- see docs/pre-production-security-todo.md for the verification notes.
set -euo pipefail

: "${POSTGRES_APP_RUNTIME_USER:?POSTGRES_APP_RUNTIME_USER must be set}"
: "${POSTGRES_APP_RUNTIME_PASSWORD:?POSTGRES_APP_RUNTIME_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${POSTGRES_APP_RUNTIME_USER}') THEN
          CREATE ROLE "${POSTGRES_APP_RUNTIME_USER}" LOGIN PASSWORD '${POSTGRES_APP_RUNTIME_PASSWORD}';
       END IF;
    END
    \$\$;

    -- Deliberately NOT granted CREATE/TEMPORARY at the database level:
    -- schema ownership below already gives this role everything it needs
    -- to create/manage objects inside its own "app" schema, and nothing
    -- outside it (verified: denied on "public" and on creating new schemas).
    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_APP_RUNTIME_USER}";
    CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION "${POSTGRES_APP_RUNTIME_USER}";
EOSQL
