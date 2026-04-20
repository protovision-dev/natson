#!/usr/bin/env bash
# Create the two app-tier roles used by the Next.js web service:
#   natson_ro    — read-only on public schema (rate grid + dashboards)
#   natson_auth  — owner of the `auth` schema (better-auth tables)
#
# Idempotent: re-runs ALTER ROLE … PASSWORD on existing roles so password
# rotations work without dropping the role.
#
# Reads passwords from the repo root .env:
#   NATSON_RO_PASSWORD=…
#   NATSON_AUTH_PASSWORD=…
#
# Usage (from repo root):
#     ./db/bootstrap-app-roles.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

# shellcheck disable=SC1091
[ -f "$ROOT_DIR/.env" ] && set -a && source "$ROOT_DIR/.env" && set +a

: "${NATSON_RO_PASSWORD:?NATSON_RO_PASSWORD must be set in .env}"
: "${NATSON_AUTH_PASSWORD:?NATSON_AUTH_PASSWORD must be set in .env}"

PG_DB="${POSTGRES_DB:-natson}"
PG_USER="${POSTGRES_USER:-natson}"
COMPOSE_SERVICE="${POSTGRES_SERVICE:-postgres}"

# psql variables substitute in plain SQL and \if conditionals, but NOT
# inside DO $$ … $$ blocks, so we use \if to gate CREATE vs ALTER ROLE.
docker compose exec -T "$COMPOSE_SERVICE" \
    psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 \
    -v ro_pw="$NATSON_RO_PASSWORD" \
    -v auth_pw="$NATSON_AUTH_PASSWORD" <<'SQL'
\set QUIET on

-- natson_ro --------------------------------------------------------
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'natson_ro')
    AS create_ro \gset
\if :create_ro
    CREATE ROLE natson_ro LOGIN PASSWORD :'ro_pw';
\else
    ALTER ROLE natson_ro WITH LOGIN PASSWORD :'ro_pw';
\endif

GRANT USAGE ON SCHEMA public TO natson_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO natson_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO natson_ro;

-- natson_auth ------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS auth;

SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'natson_auth')
    AS create_auth \gset
\if :create_auth
    CREATE ROLE natson_auth LOGIN PASSWORD :'auth_pw';
\else
    ALTER ROLE natson_auth WITH LOGIN PASSWORD :'auth_pw';
\endif

GRANT ALL ON SCHEMA auth TO natson_auth;
GRANT ALL ON ALL TABLES IN SCHEMA auth TO natson_auth;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth
    GRANT ALL ON TABLES TO natson_auth;
ALTER DEFAULT PRIVILEGES IN SCHEMA auth
    GRANT ALL ON SEQUENCES TO natson_auth;

-- Narrow write access on scrape_jobs so the web tier can:
--   - resume failed jobs (UPDATE resumed_to_job_id)        — 0021
--   - mark stuck jobs failed (UPDATE state/completed_at/   — 0022
--     exit_code/last_line)
-- natson_ro stays read-only; natson_auth gets only these specific
-- column-level UPDATEs on public.scrape_jobs.
GRANT SELECT ON public.scrape_jobs TO natson_auth;
GRANT UPDATE (resumed_to_job_id, state, completed_at, exit_code, last_line)
    ON public.scrape_jobs TO natson_auth;
SQL

echo "[bootstrap] applied app-tier roles to ${PG_DB} on ${COMPOSE_SERVICE}."
