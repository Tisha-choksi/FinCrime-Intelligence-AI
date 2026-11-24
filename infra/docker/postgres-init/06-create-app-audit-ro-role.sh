#!/usr/bin/env bash
# Creates the read-only audit role (docs/pre-production-security-todo.md
# item 3). Only the role itself is created here -- the specific SELECT
# grants on app.audit_events/app.case_history are applied by an Alembic
# migration instead (services/api/migrations/versions/*_grant_app_audit_ro*.py),
# since those tables don't exist yet at first-init time on a fresh volume.
# That migration's GRANT requires this role to already exist, hence this
# script runs before any migration ever could.
set -euo pipefail

: "${POSTGRES_APP_AUDIT_RO_USER:?POSTGRES_APP_AUDIT_RO_USER must be set}"
: "${POSTGRES_APP_AUDIT_RO_PASSWORD:?POSTGRES_APP_AUDIT_RO_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${POSTGRES_APP_AUDIT_RO_USER}') THEN
          CREATE ROLE "${POSTGRES_APP_AUDIT_RO_USER}" LOGIN PASSWORD '${POSTGRES_APP_AUDIT_RO_PASSWORD}';
       END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_APP_AUDIT_RO_USER}";
    GRANT USAGE ON SCHEMA app TO "${POSTGRES_APP_AUDIT_RO_USER}";
EOSQL
