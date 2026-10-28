#!/usr/bin/env bash
# Creates a dedicated, least-privilege role for n8n's own internal tables,
# separate from the application role (POSTGRES_USER). Runs once, on first
# init of an empty postgres data volume (see docker-entrypoint-initdb.d).
set -euo pipefail

: "${POSTGRES_N8N_USER:?POSTGRES_N8N_USER must be set}"
: "${POSTGRES_N8N_PASSWORD:?POSTGRES_N8N_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${POSTGRES_N8N_USER}') THEN
          CREATE ROLE "${POSTGRES_N8N_USER}" LOGIN PASSWORD '${POSTGRES_N8N_PASSWORD}';
       END IF;
    END
    \$\$;

    GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_N8N_USER}";
    CREATE SCHEMA IF NOT EXISTS n8n AUTHORIZATION "${POSTGRES_N8N_USER}";
EOSQL
