#!/usr/bin/env bash
# Apply pending SQL migrations from db/migrations/ to the running postgres
# service.  Tracks applied versions in schema_migrations.  Each migration
# runs in its own transaction; a failure aborts the run without touching
# later files.
#
# Usage (from repo root):
#     ./db/migrate.sh up        # apply all pending migrations
#     ./db/migrate.sh status    # show applied + pending
#     ./db/migrate.sh list      # list every migration file in order
#
# Requires `docker compose` on PATH and the `postgres` service running.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MIGRATIONS_DIR="$SCRIPT_DIR/migrations"
COMPOSE_SERVICE="${POSTGRES_SERVICE:-postgres}"
PG_DB="${POSTGRES_DB:-natson}"
PG_USER="${POSTGRES_USER:-natson}"

psql_quiet() {
    docker compose exec -T "$COMPOSE_SERVICE" \
        psql -U "$PG_USER" -d "$PG_DB" -qAtX -v ON_ERROR_STOP=1 "$@"
}

psql_file() {
    # Apply a file in a single transaction by piping it to psql.
    docker compose exec -T "$COMPOSE_SERVICE" \
        psql -U "$PG_USER" -d "$PG_DB" --single-transaction -v ON_ERROR_STOP=1 < "$1"
}

ensure_tracker() {
    # Guarantees schema_migrations exists before we inspect it.
    # 0001 is self-registering — running it twice is safe.
    psql_file "$MIGRATIONS_DIR/0001_schema_migrations.sql" >/dev/null
}

list_versions() {
    # Output "version\tfilename" for every file matching NNNN_*.sql.
    ( cd "$MIGRATIONS_DIR" && ls -1 [0-9][0-9][0-9][0-9]_*.sql 2>/dev/null | \
        awk '{ split($0, a, "_"); print a[1] "\t" $0 }' | sort )
}

applied_versions() {
    psql_quiet -c "SELECT version FROM schema_migrations ORDER BY version;"
}

preflight_pg_cron() {
    # 0007 requires pg_cron preloaded.  If it's not, halt with a clear recovery.
    local preloaded
    preloaded=$(psql_quiet -c "SHOW shared_preload_libraries;" || echo "")
    if ! grep -q 'pg_cron' <<< "$preloaded"; then
        cat >&2 <<EOF
[migrate] 0007 requires pg_cron in shared_preload_libraries but it's not loaded.
          Rebuild the postgres image and restart:
              docker compose build postgres
              docker compose up -d postgres
          Then re-run: ./db/migrate.sh up
EOF
        exit 2
    fi
}

cmd_up() {
    ensure_tracker
    local applied pending_any=0
    applied=$(applied_versions | tr '\n' ' ')

    # Materialize the file list into an array first.  Reading via process
    # substitution doesn't work cleanly here: `docker compose exec -T`
    # inside the loop consumes stdin from the outer redirect and kills
    # subsequent iterations.
    local -a entries=()
    while IFS= read -r line; do
        entries+=("$line")
    done < <(list_versions)

    for line in "${entries[@]}"; do
        [[ -z "$line" ]] && continue
        local version filename
        version="${line%%$'\t'*}"
        filename="${line#*$'\t'}"
        if [[ " $applied " == *" $version "* ]]; then
            continue
        fi
        pending_any=1
        echo "[migrate] applying $filename"

        # Per-migration preflight hooks.
        if [[ "$version" == "0007" ]]; then
            preflight_pg_cron
        fi

        if ! psql_file "$MIGRATIONS_DIR/$filename"; then
            echo "[migrate] FAILED on $filename — aborting" >&2
            exit 1
        fi
        psql_quiet -c \
            "INSERT INTO schema_migrations (version, filename) VALUES ('$version', '$filename') ON CONFLICT (version) DO NOTHING;"
    done

    if (( pending_any == 0 )); then
        echo "[migrate] up to date — no pending migrations"
    fi
}

cmd_status() {
    ensure_tracker
    local applied
    applied=$(applied_versions | tr '\n' ' ')
    printf "%-8s  %-12s  %s\n" "VERSION" "STATE" "FILE"
    printf "%-8s  %-12s  %s\n" "-------" "-----" "----"
    while IFS=$'\t' read -r version filename; do
        [[ -z "$version" ]] && continue
        if [[ " $applied " == *" $version "* ]]; then
            state="applied"
        else
            state="pending"
        fi
        printf "%-8s  %-12s  %s\n" "$version" "$state" "$filename"
    done < <(list_versions)
}

cmd_list() {
    list_versions | awk -F'\t' '{ printf "%-8s  %s\n", $1, $2 }'
}

case "${1:-up}" in
    up)     cmd_up     ;;
    status) cmd_status ;;
    list)   cmd_list   ;;
    *)      echo "usage: $0 [up|status|list]" >&2; exit 2 ;;
esac
