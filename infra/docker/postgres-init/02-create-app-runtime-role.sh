#!/usr/bin/env bash
# Creates a non-superuser runtime role for services/api. The bootstrap
# role (POSTGRES_USER) remains superuser for image init/migrations only;
# the running API must never connect as it.
#
# Sprint 4 change: this role no longer OWNS schema "app" -- ownership
# moved to app_migrator (05-create-app-migrator-role.sh), which also
# grants this role DML (not DDL) on it. On a fresh volume, run scripts in
# numeric order (02 before 05) so this role exists before 05 grants it
# anything. See docs/pre-production-security-todo.md item 2 and
# docs/sprint-4-identity-and-authz.md for the verification notes.
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

    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_APP_RUNTIME_USER}";
EOSQL
