#!/usr/bin/env bash
# Creates a dedicated, least-privilege role for Keycloak's own internal
# tables, mirroring the n8n_internal/n8n isolation pattern (01-create-n8n-role.sh).
# Runs once, on first init of an empty postgres data volume.
set -euo pipefail

: "${POSTGRES_KEYCLOAK_USER:?POSTGRES_KEYCLOAK_USER must be set}"
: "${POSTGRES_KEYCLOAK_PASSWORD:?POSTGRES_KEYCLOAK_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${POSTGRES_KEYCLOAK_USER}') THEN
          CREATE ROLE "${POSTGRES_KEYCLOAK_USER}" LOGIN PASSWORD '${POSTGRES_KEYCLOAK_PASSWORD}';
       END IF;
    END
    \$\$;

    -- Same Postgres 15+ rationale as the n8n role: Keycloak's own schema
    -- migrations need CREATE/TEMPORARY at the database level even though
    -- it also owns its own schema.
    GRANT CONNECT, CREATE, TEMPORARY ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_KEYCLOAK_USER}";
    CREATE SCHEMA IF NOT EXISTS keycloak AUTHORIZATION "${POSTGRES_KEYCLOAK_USER}";
EOSQL
