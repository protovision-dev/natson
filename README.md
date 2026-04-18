# Natson Hotels — Lighthouse rate-intelligence stack

A production-oriented pipeline that pulls daily competitor room rates from
[Lighthouse](https://app.mylighthouse.com) for Natson's 10 portfolio
properties, stores them for trend analysis, and will surface them through
Metabase for internal BI.

> Full architecture, decisions, and open items live in
> [`roadmap.md`](./roadmap.md). This README is the quick-start.

## The stack

| Service | Role | URL |
|---|---|---|
| `browser-api` | FastAPI + Camoufox login/scrape service | http://localhost:8765 |
| `scraper` | Python — runs Job-driven scrapes; idle by default | invoked via `docker compose run` |
| `scraper-login` | Long-running login daemon (Phase 4 — placeholder today) | — |
| `postgres` | Main datastore (`natson` + `metabase` DBs) | localhost:5432 |
| `metabase` | Self-service BI on Postgres | http://localhost:3010 |

All five live in one `docker-compose.yml` at the repo root, sharing a
`natson` bridge network.

## Phase status

| Phase | Status | What's in |
|---|---|---|
| 1 — Git bootstrap + secret hygiene | ✅ | `.gitignore`, `.env.example`, compose reads creds from `.env` |
| 2 — Compose + Postgres + Metabase scaffold | ✅ | five-service stack, `docker compose up -d` brings it healthy |
| 3 — Flexible `run_job.py` + Job abstraction | ✅ | every URL param is a flag; concurrent-safe via fcntl locks |
| 4 — Login daemon + portfolio admin | ✅ | `scraper-login` auto-refreshes `session.json`; `admin.py` manages `hotels.json` |
| 5 — Postgres write path | ⏳ | schema from user; DAL goes in `scraper/db/` |
| 6 — Metabase dashboards + optional Jobs API | ✅ (dashboards) / ⏳ (Jobs API) | `metabase/provision.py` stands up the admin + DB + two dashboards idempotently |

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

**Metabase hook-up (one-time, scripted):**

```bash
docker compose run --rm \
    -v "$PWD/metabase:/metabase:ro" \
    -e METABASE_URL=http://metabase:3000 \
    scraper python /metabase/provision.py
```

That script is **idempotent** — it uses the first-boot setup token if
Metabase hasn't been touched, else logs in with `METABASE_ADMIN_*`
creds from `.env`. It creates the admin account, wires the Postgres
connection, and builds two dashboards:

- **Active scrapes** (http://localhost:3010/dashboard/2) — live count +
  per-job progress table. Refresh the page to poll.
- **Scrape history** (http://localhost:3010/dashboard/3) — jobs by
  state (pie), completed scrapes by OTA (bar), jobs per day (stacked
  line), and the last-100 table.

Log in with the `METABASE_ADMIN_EMAIL` / `PASSWORD` from your `.env`
(defaults `admin@natson.local` / placeholder — change for production).

The filesystem fallback — `scraper/output/jobs/{job_id}/{status.json,
spec.json, run.log}` — is still written on every run, so
non-Metabase tools (CLI grep, `tail -f`, whatever) keep working. DB
writes silently no-op if Postgres is unreachable, so a Postgres blip
never kills a running scrape.

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
├── db/init/           Postgres init: extensions + metabase DB bootstrap
├── docker-compose.yml The stack
├── .env.example       Shape of the gitignored .env
└── roadmap.md         Full plan: decisions, phases, verification
```

## Configuration

- `.env` at the root — Postgres, Metabase, Lighthouse, proxy, Firecrawl
  creds. **Never committed.**
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
- **Metabase port collision** — 3000 is often taken by other tools.
  We default to 3010 in `.env.example`; override `METABASE_PORT` to
  pick another port.
