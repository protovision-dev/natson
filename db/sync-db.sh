#!/usr/bin/env bash
# db/sync-db.sh — move the natson Postgres DB between local dev and
# the production VPS. Single command per direction, with a destination
# snapshot taken first as a rollback path.
#
# Usage:
#   db/sync-db.sh dump              snapshot local DB → backups/local-<ts>.dump
#   db/sync-db.sh pull              prod  → local (DESTRUCTIVE, asks first)
#   db/sync-db.sh push              local → prod  (DESTRUCTIVE, asks first)
#   db/sync-db.sh restore <file>    restore a local backup file into local DB
#
# Reads from repo-root .env:
#   POSTGRES_DB / POSTGRES_USER         already required by the stack
#   PROD_HOST                           VPS hostname (e.g. natson.protovision.app)
#   PROD_SSH_USER  default: deploy
#   PROD_REPO_PATH default: /srv/natsonhotels
#
# What's excluded by default (and why):
#   - auth.user / session / account / verification   tied to BETTER_AUTH_SECRET
#   - scrape_jobs                                     job ids are per-environment
# Override with INCLUDE_AUTH=1 / INCLUDE_JOBS=1 if you really want them.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
BACKUPS_DIR="$ROOT_DIR/backups"
mkdir -p "$BACKUPS_DIR"

# Read a single var from .env without sourcing the whole file. Sourcing
# explodes on values containing shell metacharacters like the unquoted
# angle brackets in RESEND_FROM=Natson <noreply@…>.
read_env() {
    local var="$1"; local def="${2:-}"
    local val=""
    if [ -f "$ROOT_DIR/.env" ]; then
        val=$(grep -E "^${var}=" "$ROOT_DIR/.env" 2>/dev/null | tail -1 \
              | cut -d= -f2- | sed -E "s/^['\"](.*)['\"]\$/\\1/")
    fi
    # Real shell-env value (if exported) overrides the .env value.
    eval "echo \"\${${var}:-${val:-$def}}\""
}

PG_DB=$(read_env POSTGRES_DB natson)
PG_USER=$(read_env POSTGRES_USER natson)
PROD_HOST=$(read_env PROD_HOST)
PROD_SSH_USER=$(read_env PROD_SSH_USER deploy)
PROD_REPO_PATH=$(read_env PROD_REPO_PATH /srv/natsonhotels)
INCLUDE_AUTH=$(read_env INCLUDE_AUTH 0)
INCLUDE_JOBS=$(read_env INCLUDE_JOBS 0)

ts() { date -u +%Y%m%dT%H%M%SZ; }

# Build the pg_dump exclude flags based on env toggles.
dump_excludes() {
    local args=()
    if [ "$INCLUDE_AUTH" != "1" ]; then
        args+=(--exclude-table-data 'auth.user')
        args+=(--exclude-table-data 'auth.session')
        args+=(--exclude-table-data 'auth.account')
        args+=(--exclude-table-data 'auth.verification')
    fi
    if [ "$INCLUDE_JOBS" != "1" ]; then
        args+=(--exclude-table-data 'public.scrape_jobs')
    fi
    printf '%s\n' "${args[@]}"
}

confirm() {
    local prompt="$1"
    read -r -p "$prompt [type 'yes' to proceed]: " ans
    [ "$ans" = "yes" ] || { echo "aborted"; exit 1; }
}

require_prod_host() {
    if [ -z "${PROD_HOST:-}" ]; then
        echo "PROD_HOST not set in .env" >&2
        exit 2
    fi
}

# --- subcommands -----------------------------------------------------

cmd_dump() {
    local out="$BACKUPS_DIR/local-$(ts).dump"
    # shellcheck disable=SC2046
    docker compose exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" -Fc \
        $(dump_excludes) > "$out"
    echo "→ $out ($(du -h "$out" | cut -f1))"
}

cmd_pull() {
    require_prod_host
    local snap="$BACKUPS_DIR/prod-$(ts).dump"
    local local_safety="$BACKUPS_DIR/local-pre-pull-$(ts).dump"

    echo "[1/4] snapshot prod → $snap"
    ssh "${PROD_SSH_USER}@${PROD_HOST}" \
        "cd $PROD_REPO_PATH && docker compose exec -T postgres pg_dump -U $PG_USER -d $PG_DB -Fc $(dump_excludes | tr '\n' ' ')" \
        > "$snap"
    echo "    snapshot size: $(du -h "$snap" | cut -f1)"

    echo "[2/4] safety snapshot of local → $local_safety"
    docker compose exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" -Fc \
        > "$local_safety"

    echo "[3/4] confirm restore (will OVERWRITE local DB)"
    confirm "restore prod snapshot into local '$PG_DB'?"

    echo "[4/4] restoring..."
    docker compose exec -T postgres pg_restore -U "$PG_USER" -d "$PG_DB" \
        --clean --if-exists --no-owner --no-privileges --single-transaction \
        < "$snap"
    echo "✓ pulled prod → local. rollback: $local_safety"
}

cmd_push() {
    require_prod_host
    local snap="$BACKUPS_DIR/local-$(ts).dump"
    local prod_safety="prod-pre-push-$(ts).dump"

    echo "[1/4] snapshot local → $snap"
    # shellcheck disable=SC2046
    docker compose exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" -Fc \
        $(dump_excludes) > "$snap"
    echo "    snapshot size: $(du -h "$snap" | cut -f1)"

    echo "[2/4] safety snapshot on PROD → ${PROD_REPO_PATH}/backups/${prod_safety}"
    ssh "${PROD_SSH_USER}@${PROD_HOST}" \
        "cd $PROD_REPO_PATH && docker compose exec -T postgres pg_dump -U $PG_USER -d $PG_DB -Fc > backups/${prod_safety}"

    echo "[3/4] confirm restore (will OVERWRITE PROD DB on ${PROD_HOST})"
    confirm "push local snapshot to prod, OVERWRITING ${PG_DB} on ${PROD_HOST}?"

    echo "[4/4] streaming + restoring on prod..."
    ssh "${PROD_SSH_USER}@${PROD_HOST}" \
        "cd $PROD_REPO_PATH && docker compose exec -T postgres pg_restore -U $PG_USER -d $PG_DB --clean --if-exists --no-owner --no-privileges --single-transaction" \
        < "$snap"
    echo "✓ pushed local → prod. prod rollback: ${PROD_REPO_PATH}/backups/${prod_safety}"
}

cmd_restore() {
    local file="${1:-}"
    [ -f "$file" ] || { echo "file not found: $file" >&2; exit 2; }

    local local_safety="$BACKUPS_DIR/local-pre-restore-$(ts).dump"
    echo "[1/3] safety snapshot of current local → $local_safety"
    docker compose exec -T postgres pg_dump -U "$PG_USER" -d "$PG_DB" -Fc \
        > "$local_safety"

    echo "[2/3] confirm restore"
    confirm "restore $file into local '$PG_DB'?"

    echo "[3/3] restoring..."
    docker compose exec -T postgres pg_restore -U "$PG_USER" -d "$PG_DB" \
        --clean --if-exists --no-owner --no-privileges --single-transaction \
        < "$file"
    echo "✓ restored. rollback: $local_safety"
}

# --- dispatch --------------------------------------------------------

case "${1:-}" in
    dump)    shift; cmd_dump "$@" ;;
    pull)    shift; cmd_pull "$@" ;;
    push)    shift; cmd_push "$@" ;;
    restore) shift; cmd_restore "$@" ;;
    *) sed -n '2,/^$/p' "$0"; exit 1 ;;
esac
