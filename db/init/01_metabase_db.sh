#!/bin/bash
# Create a separate database + role for Metabase's internal state, so
# Metabase's schema doesn't live next to scrape data.
# Runs once on fresh pg_data volume; noop on restart.

set -euo pipefail

: "${METABASE_DB:?METABASE_DB not set}"
: "${METABASE_DB_USER:?METABASE_DB_USER not set}"
: "${METABASE_DB_PASSWORD:?METABASE_DB_PASSWORD not set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER ${METABASE_DB_USER} WITH PASSWORD '${METABASE_DB_PASSWORD}';
    CREATE DATABASE ${METABASE_DB} OWNER ${METABASE_DB_USER};
    GRANT ALL PRIVILEGES ON DATABASE ${METABASE_DB} TO ${METABASE_DB_USER};
EOSQL
