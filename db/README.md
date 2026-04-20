# Database migrations + init

Two disjoint paths feed Postgres:

- **`db/init/`** — only runs on a **fresh `pg_data` volume** (the official
  `postgres` image's `/docker-entrypoint-initdb.d` convention). Extensions
  and the legacy `scrape_jobs` table. Don't put evolving schema here —
  blowing away the volume is the only way to re-run these, and that
  destroys data.
- **`db/migrations/`** — versioned SQL files applied by `db/migrate.sh`
  against an already-running `postgres` service. Idempotent via a
  `schema_migrations` tracking table.

## Running migrations

From the repo root, with the stack up (`docker compose up -d postgres`):

```bash
./db/migrate.sh status    # which migrations are applied vs pending
./db/migrate.sh up        # apply everything pending, in order
./db/migrate.sh list      # just list the migration files
```

Each file runs in a single transaction; a failure aborts the run and
later files are not applied. Re-running is safe — applied versions are
skipped.

## File convention

```
db/migrations/NNNN_short_name.sql
```

where `NNNN` is a zero-padded 4-digit sequence (`0001`, `0002`, …). The
runner orders files lexicographically, so the sequence determines the
application order. Skip numbers if you need to (e.g. jump from `0007`
to `0010`) — just keep the digits monotonic.

## Preflight hooks

Some migrations need special readiness checks. These are coded as
per-version hooks in `migrate.sh`:

| Version | Requires |
|---|---|
| `0007_partition_automation.sql` | `pg_cron` in `shared_preload_libraries` (see `postgres/postgresql.conf`). If the stack was not rebuilt after switching to the custom postgres image, the runner halts with the exact recovery command. |

## Syncing data between dev and prod

`db/sync-db.sh` is a one-command shim around `pg_dump` + `pg_restore`
for moving the natson DB between local docker and the VPS. Always
takes a "rollback" snapshot of the destination before the destructive
restore.

```bash
./db/sync-db.sh dump              # local snapshot → backups/local-<ts>.dump
./db/sync-db.sh pull              # prod  → local (asks; safety-snapshots local first)
./db/sync-db.sh push              # local → prod  (asks; safety-snapshots prod first)
./db/sync-db.sh restore <file>    # restore a local file into local
```

Prod coords come from repo-root `.env`:

```
PROD_HOST=natson.protovision.app
PROD_SSH_USER=deploy
PROD_REPO_PATH=/srv/natsonhotels
```

What the script **excludes by default** (and why):

| Excluded | Reason |
|---|---|
| `auth.user`, `auth.session`, `auth.account`, `auth.verification` | Password hashes are bound to `BETTER_AUTH_SECRET`. Migrating across envs silently locks everyone out — sign up fresh in each env. |
| `public.scrape_jobs` | Job IDs are per-environment runtime state, not a useful migration. |

Override with `INCLUDE_AUTH=1` or `INCLUDE_JOBS=1` if you really mean it.

**Recovery from a botched sync:**

```bash
# pull went sideways → local is wrong, restore from the safety snapshot
./db/sync-db.sh restore backups/local-pre-pull-<ts>.dump

# push went sideways → on the VPS
docker compose exec -T postgres pg_restore -U natson -d natson \
    --clean --if-exists < backups/prod-pre-push-<ts>.dump
```

## Authoring a new migration

1. Copy the highest-numbered existing file to the next version.
2. Write idempotent SQL (`CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO
   NOTHING`, etc.) — the runner protects against double-application, but
   belt + braces is cheap.
3. `./db/migrate.sh up` from repo root.

## What lives where

| Area | File |
|---|---|
| Extensions | `db/init/00_extensions.sql` (fresh volume), `db/migrations/0002_extensions.sql` (runtime) |
| Legacy job state | `db/init/02_scrape_jobs.sql` |
| App-tier roles (`natson_ro`, `natson_auth`) | `db/bootstrap-app-roles.sh` (env-driven, idempotent) |
| better-auth schema | `db/migrations/0016_auth_schema.sql` + `0017_better_auth_tables.sql` |
| Dev↔prod data sync | `db/sync-db.sh push|pull|dump|restore` |
| Rate-tracking dimensions | `db/migrations/0003_dimensions.sql` |
| Scrape run audit | `db/migrations/0004_scrape_runs.sql` |
| Rate fact tables | `db/migrations/0005_facts.sql` |
| Partition bootstrap | `db/migrations/0006_partitions_bootstrap.sql` |
| Auto-rolling partitions (pg_cron) | `db/migrations/0007_partition_automation.sql` |
| Subject hotel seed | `db/migrations/0008_seed_subjects.sql` |
| Reporting views | `db/migrations/0009_views.sql` |
