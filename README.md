# Natson Hotels — Lighthouse rate-intelligence stack

A production-oriented pipeline that pulls daily competitor room rates from
[Lighthouse](https://app.mylighthouse.com) for Natson's 10 portfolio
properties, stores them for trend analysis, and surfaces them through a
custom React frontend modeled on Lighthouse's own rate grid.

> Full architecture, decisions, and open items live in
> [`roadmap.md`](./roadmap.md). This README is the quick-start.

## The stack

| Service | Role | URL |
|---|---|---|
| `browser-api` | FastAPI + Camoufox login/scrape service | http://localhost:8765 |
| `scraper` | Python — runs Job-driven scrapes; idle by default | invoked via `docker compose run` |
| `scraper-login` | Long-running login daemon — auto-refreshes `session.json` | — |
| `postgres` | Main datastore (`natson` DB + `auth` schema) | localhost:5432 |
| `jobs-api` | Thin FastAPI sidecar that spawns `run_job.py` on demand | http://localhost:8770 |
| `web` | Next.js 15 + better-auth — Lighthouse-style rate grid + jobs UI | http://localhost:3020 |

All six live in one `docker-compose.yml` at the repo root, sharing a
`natson` bridge network.

## Phase status

| Phase | Status | What's in |
|---|---|---|
| 1 — Git bootstrap + secret hygiene | ✅ | `.gitignore`, `.env.example`, compose reads creds from `.env` |
| 2 — Compose + Postgres scaffold | ✅ | container stack, `docker compose up -d` brings it healthy |
| 3 — Flexible `run_job.py` + Job abstraction | ✅ | every URL param is a flag; concurrent-safe via fcntl locks |
| 4 — Login daemon + portfolio admin | ✅ | `scraper-login` auto-refreshes `session.json`; `admin.py` manages `hotels.json` |
| 5 — Postgres rates ingest | ✅ | `scraper/db/ingest.py` dual-writes snapshots; `db/migrate.sh` runs SQL migrations; pg_cron auto-rolls monthly partitions |
| 6 — Metabase dashboards | ✅ then removed | superseded by Phase 7; metabase service + DB dropped on `feat/web-frontend` |
| 7 — React frontend + Jobs API | ✅ | Next.js 15 grid + better-auth + jobs-api sidecar; replaces Metabase |

## Quick start

```bash
# 1. One-time: real creds land in gitignored .env files
cp .env.example .env
cp browser-api/.env.example browser-api/.env
# edit each .env with real values

# 2. Bring up the stack
docker compose up -d

# 3. Session lands automatically — the `scraper-login` daemon will log in
#    via browser-api on first boot and keep session.json fresh (24h TTL,
#    relogins when <2h remain). Check with:
docker compose run --rm scraper python admin.py session

# 4. Fire a scrape job
docker compose run --rm scraper python run_job.py \
    --hotels portfolio --dates rolling:2 --ota bookingdotcom --refresh
```

Output lands in the `session_vol` docker volume, viewable via
`docker compose exec scraper ls /app/output/snapshots/<date>/`.

## Running scrape jobs

One `docker compose run` = one Job. Every URL variable is a flag;
anything omitted falls back to [`scraper/scraper.config.yml`](./scraper/scraper.config.yml).

```bash
# All portfolio hotels, May 2026, Booking.com, with fresh refresh
docker compose run --rm scraper python run_job.py \
    --hotels portfolio --dates 2026-05 --ota bookingdotcom --refresh

# One hotel, one date, LOS=1, 1 person, brand.com — warm (no refresh)
docker compose run --rm scraper python run_job.py \
    --hotels 345062 --dates 2026-05-15 --los 1 --persons 1 \
    --ota branddotcom --no-refresh

# Refresh only — trigger /liveshop + poll, skip rate fetch
docker compose run --rm scraper python run_job.py \
    --hotels portfolio --dates rolling:2 --refresh-only

# Fire three concurrent jobs, one per month
for M in 2026-04 2026-05 2026-06; do
    docker compose run --rm -d scraper python run_job.py \
        --hotels portfolio --dates $M --ota bookingdotcom --refresh &
    sleep 3
done
wait
```

### `--dates`

| Form | Example | Meaning |
|---|---|---|
| Single date | `2026-05-15` | One check-in |
| Date range | `2026-05-01:2026-05-31` | Inclusive |
| Month | `2026-05` | Full month |
| Month range | `2026-05:2026-07` | Inclusive on both ends |
| Rolling window | `rolling:2` | Current month + next N |

### `--hotels`

| Form | Meaning |
|---|---|
| `345062,345069` | Explicit subscription IDs (must exist in `hotels.json`) |
| `portfolio` | Every entry in `hotels.json` |
| `file:path.json` | Alternate file in the same shape |

### Refresh modes

- `--refresh` — trigger `/liveshop` + poll until complete, then fetch rates.
- `--no-refresh` — skip the refresh, fetch whatever Lighthouse has (warm path).
- `--refresh-only` — trigger + poll, skip fetch (stage fresh data for a later job).

## Database migrations

Schema evolves via `db/migrate.sh`:

```bash
./db/migrate.sh status    # show applied + pending
./db/migrate.sh up        # apply everything pending
./db/migrate.sh list      # list migration files
```

Each file in `db/migrations/NNNN_*.sql` runs in a single transaction,
idempotently. Applied versions are tracked in `schema_migrations`.

Partition maintenance is automated: `pg_cron` inside Postgres runs
`ensure_rate_obs_partitions(9)` on the 1st of every month. No external
cron or user action needed.

## Backfilling Postgres from JSON

If the DB gets out of sync with the authoritative on-disk snapshots
(e.g. `WRITE_DB=0` for a while, or a new schema needs replaying),
`reconcile.py` walks the JSON tree and re-ingests:

```bash
docker compose run --rm scraper python reconcile.py --date 2026-04-18
docker compose run --rm scraper python reconcile.py --since 2026-04-01 --until 2026-04-18
docker compose run --rm scraper python reconcile.py --date 2026-04-18 --hotel 345062 --ota branddotcom
docker compose run --rm scraper python reconcile.py --date 2026-04-18 --dry-run
```

Ingest is idempotent (UPSERT on the natural key + observation_date),
so re-runs are safe.

## Monitoring scrapes

Every job writes its state to **Postgres** (and a mirror `status.json`
on disk). Concurrent jobs show up in the `active_scrapes` view;
history lives in `recent_scrapes`.

```sql
-- Everything currently running
SELECT * FROM active_scrapes;

-- Last 200 jobs with durations
SELECT * FROM recent_scrapes;
```

**Web UI (the primary surface):**

```
http://localhost:3020
```

First time: `/signup` → land on `/grid`. better-auth users live in the
`auth` schema of the `natson` DB.

- **`/grid`** — Lighthouse-style rate grid: rows = check-in dates,
  three frozen-left columns (Date, Market demand, Subject Property)
  with a freeze line, competitors scroll horizontally to the right.
  Today's row highlighted orange. Filter bar drives subject / OTA /
  nights / guests / from-month via URL params. **Refresh rates**
  button shells to `jobs-api`, polls until the scrape completes, then
  silently re-renders.
- **`/jobs`** — active + recent scrapes from `active_scrapes` /
  `recent_scrapes` views; auto-refreshes every 10s.

**One-time DB setup for the web tier:**

```bash
./db/migrate.sh up                  # creates auth schema + tables
./db/bootstrap-app-roles.sh         # creates natson_ro + natson_auth
```

Both are idempotent. Passwords come from `.env` (`NATSON_RO_PASSWORD`,
`NATSON_AUTH_PASSWORD`).

The filesystem fallback — `scraper/output/jobs/{job_id}/{status.json,
spec.json, run.log}` — is still written on every run, so CLI tools
(`grep`, `tail -f`, whatever) keep working. DB writes silently no-op
if Postgres is unreachable, so a Postgres blip never kills a running
scrape.

## Repo layout

```
natsonhotels/
├── browser-api/       FastAPI + Camoufox login service (Docker)
├── scraper/           Python scraper (Docker); jobs/ submodule for CLI/parsers
│   ├── jobs/          spec.py | dates.py | hotels.py | locks.py
│   ├── scraper.config.yml     all URL-param defaults
│   ├── run_job.py     entrypoint
│   ├── db/            Postgres DAL (connection.py, jobs.py)
│   ├── config.py | refresh.py | scrape.py | snapshot.py | login.py
│   └── hotels.json    portfolio subscription list
├── booking/           Parked Booking.com scripts (Firecrawl + direct browser)
├── db/                Migrations + bootstrap script for app-tier roles
│   ├── init/          Postgres extensions (run on first boot)
│   ├── migrations/    Versioned SQL applied via db/migrate.sh
│   └── bootstrap-app-roles.sh   Creates natson_ro + natson_auth from .env
├── jobs-api/          FastAPI sidecar; spawns run_job.py on demand
├── web/               Next.js 15 frontend (rate grid + jobs UI + better-auth)
├── docker-compose.yml The stack
├── .env.example       Shape of the gitignored .env
└── roadmap.md         Full plan: decisions, phases, verification
```

## Configuration

- `.env` at the root — Postgres, Lighthouse, proxy, Firecrawl, web-tier
  (better-auth secret + app-role passwords). **Never committed.**
- `browser-api/.env` — Camoufox + proxy. **Never committed.**
- `scraper/scraper.config.yml` — default URL params + pacing. Committed.
- `scraper/hotels.json` — portfolio subscriptions. Committed.

## Portfolio admin

`hotels.json` is bind-mounted so changes persist to the host (and git).

```bash
docker compose run --rm scraper python admin.py list
docker compose run --rm scraper python admin.py add 409987 "New Studio 6 - Somewhere"
docker compose run --rm scraper python admin.py remove 409987
docker compose run --rm scraper python admin.py session
```

Only hotels listed here can drive `/rates/` + `/liveshop` — other
hotelinfos appear as compset competitors inside a portfolio scrape.

## Troubleshooting

- **`session.json missing` / scrape errors with 401** — check
  `docker compose logs scraper-login`; the daemon re-logs in on every
  tick. If LH_USER / LH_PASS aren't set in `.env`, login fails.
- **`rate-limit flags active`** — Lighthouse reflects your own running
  refresh back as "concurrent monthshop" while it runs; not a block.
  See [`scraper/api.md`](./scraper/api.md) §4.
- **Web port collision** — 3000 is commonly taken by other tools
  (open-webui, generic Node services). We default to 3020 in
  `.env.example`; override `WEB_PORT` to pick another port (and
  update `BETTER_AUTH_URL` to match).
