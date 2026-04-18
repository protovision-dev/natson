# Natson Hotels — Lighthouse Scraper → Production Stack

Living spec for turning the Lighthouse rate scraper into a small enterprise
BI app: fully containerized, flexible job-driven scraping, concurrent runs,
Postgres persistence, Metabase visualization.

## Current state (end of 2026-04-17)

**On `refactor/dockerize-stack` — 7 commits, phases 1-4 done + Phase 6
dashboards landed ahead of schedule. Only Phase 5 (full rates-schema
DAL) remains.**

- **Stack is live via `docker compose up -d`** — five services healthy:
  browser-api (8765), scraper (idle / invoked per job), scraper-login
  (auto-refreshes `session.json`), postgres 16, metabase (3010).
- **10 portfolio hotels** ("subscriptions" in Lighthouse terms) — only
  these can drive `/rates/` and `/liveshop` calls. The 71 "accessible"
  hotels in `scraper/output/accessible_hotels.json` are compset
  competitors observed inside portfolio scrapes; read-only siblings.
- **Every URL variable is a CLI flag** on `run_job.py`. Defaults in
  `scraper/scraper.config.yml`. `--hotels` / `--dates` / `--ota` /
  `--los` / `--persons` / `--refresh` (+ `--no-refresh`,
  `--refresh-only`) / `--compset-id` / `--mealtype` /
  `--membershiptype` / `--platform` / `--roomtype` / `--bar` /
  `--flexible` / `--rate-type` / `--meta`.
- **Concurrent jobs work.** Each `docker compose run --rm scraper ...`
  spawns an ephemeral container; per-(hotel, ota) fcntl locks in
  `output/locks/` keep them from stepping on each other.
- **Live Metabase dashboards** at
  http://localhost:3010/dashboard/2#refresh=30 (Active scrapes) and
  http://localhost:3010/dashboard/3#refresh=60 (Scrape history).
  `#refresh=N` makes Metabase auto-poll Postgres every N seconds.
- **Two OTAs proven:** `bookingdotcom` (7,007 cells) and `branddotcom`
  (7,735 cells) captured cleanly earlier in the day.
- **End-of-day smoke:** portfolio × 2026-05 × `--no-refresh` ran
  clean in 179s — 10/10 hotels, 2,635 rate cells, row persisted in
  `scrape_jobs`, visible in both dashboards.

## Key design decisions

| | Choice | Why |
|---|---|---|
| Concurrency | `docker compose run --rm scraper run_job ...` per job | No new service; filesystem is state until Postgres lands. |
| Hotel list | Portfolio-driven (10 today), add/remove via admin CLI; accessible set auto-merged for reporting | Matches Lighthouse access model. |
| Session | Shared `session.json` volume + separate `scraper-login` daemon service | One login/day minimizes Camoufox churn and bot fingerprints. |
| Config split | `hotels.json` = subscription list; `scraper.config.yml` = param defaults | Clean ownership; YAML friendly for humans. |
| Refresh toggle | Every job carries a `do_refresh` bool (`--refresh` / `--no-refresh`, default in YAML); also `--refresh-only` mode | Today's `--no-refresh` preserved; warm-up jobs possible. |
| Guardrails | Per-(hotel, ota) `fcntl.flock` in `output/locks/` | Prevents two jobs contending on Lighthouse's brand-shop concurrency bucket. |
| Postgres | Scaffold service now, schema arrives from user later | DAL stubbed; JSON stays primary until schema lands. |

## CLI surface (target shape)

```
# Single-hotel spot scrape
docker compose run --rm scraper python run_job.py \
    --hotels 345062 --dates 2026-05-15 --los 1 --persons 1 \
    --ota branddotcom --refresh

# Full portfolio, one month, all defaults
docker compose run --rm scraper python run_job.py \
    --hotels portfolio --dates 2026-05

# Fire three concurrent jobs, one per month, 3s jitter apart
for M in 2026-04 2026-05 2026-06; do
    docker compose run --rm -d scraper python run_job.py \
        --hotels portfolio --dates $M --ota bookingdotcom --refresh &
    sleep 3
done
wait
```

**`--dates` accepts:** `2026-05-01` | `2026-05-01:2026-05-31` |
`2026-05` | `2026-05:2026-07` | `rolling:3`

**`--hotels` accepts:** `345062,345069` | `portfolio` | `file:path.json`

**Tunable URL params:** `--los`, `--persons`, `--compset-id`, `--ota`,
`--platform`, `--mealtype`, `--membershiptype`, `--roomtype`, `--bar`,
`--flexible`, `--rate-type`. Unset ones fall back to
`scraper/scraper.config.yml`.

**Refresh modes:** `--refresh` (trigger + poll + fetch), `--no-refresh`
(fetch only — warm path), `--refresh-only` (trigger + poll, no fetch).

## Phases

Each phase = one commit on `refactor/dockerize-stack`.

### Phase 1 — Git bootstrap + secret hygiene + roadmap ✅

- `.gitignore` excludes output/, venvs, secrets, scratch files.
- Proxy creds moved from `browser-api/compose.yaml` into
  `browser-api/.env` (gitignored). `.env.example` committed.
- Firecrawl API-key fallback removed from `scraper/compare_month.py`.
- This document rewritten.
- `git init -b main`, initial commit, branch `refactor/dockerize-stack`.

### Phase 2 — Root compose + Postgres + Metabase scaffold ✅

- `docker-compose.yml` at repo root with services: `browser-api`,
  `scraper`, `scraper-login`, `postgres` (16), `metabase`.
- `scraper/Dockerfile` (python:3.12-slim, sleep infinity default CMD).
- `scraper/requirements.txt` pinned.
- `.env.example` at root (Postgres + Metabase creds, Lighthouse user/pass).
- Named volumes: `pg_data`, `metabase_data`, `session_vol`.
- `db/init/00_extensions.sql` + `db/init/01_metabase_db.sh` (creates
  the `metabase` DB + role inside the main Postgres instance).
- `METABASE_PORT` defaults to 3010 (3000 collides with open-webui in
  common local setups).

### Phase 3 — Config file + Job abstraction + `run_job` CLI + Metabase-visible job state ✅

- `scraper/scraper.config.yml` — all URL-param defaults + pacing.
- `scraper/jobs/` module — `spec.py` (Job dataclass),
  `dates.py` (5-syntax parser + ≤31-day window splitter),
  `hotels.py` (resolver + admin add/remove), `locks.py`
  (per-(hotel, ota) flock), `status.py` (filesystem + Postgres
  state writer).
- `scraper/run_job.py` — new entrypoint; honors `do_refresh` +
  `refresh-only`; writes resolved spec to
  `output/jobs/{job_id}/spec.json` for reproducibility and tees
  stdout to `output/jobs/{job_id}/run.log`.
- `config.py` URL builder: every param becomes a kwarg.
- `refresh.py`: `trigger_refresh(params: dict)`.
- `scrape.py`: becomes a library (`scrape_hotel(job, hotel_id, sess)`);
  old argparse moves to `run_job.py`. Legacy flags kept as shortcuts.
- `snapshot.py`: filename gains `job_id`.
- **Job state → Postgres (pulled forward from Phase 5):**
  `db/init/02_scrape_jobs.sql` creates `scrape_jobs` table +
  `active_scrapes` / `recent_scrapes` views. `scraper/db/`
  (connection.py, jobs.py) upserts a row on every Job state
  transition so Metabase can render live progress across concurrent
  jobs. Falls back silently if Postgres is unreachable.

### Phase 4 — Login daemon + portfolio admin ✅

- `scraper/login.py` refactored into a reusable `login()` function
  that writes `logged_in_at` + `session_ttl_s` in the session file.
- `scraper/login_daemon.py`: check session age every
  `LOGIN_CHECK_INTERVAL_S` (default 900s); re-login when remaining TTL
  drops below `LOGIN_MARGIN_S` (default 7200s) or when the file is
  missing/unreadable. Runs as the `scraper-login` compose service with
  `restart: unless-stopped`.
- `scraper/admin.py`: subcommands `list`, `add <id> <name...>`,
  `remove <id>`, `session` (shows TTL remaining).
- `scraper/hotels.json` bind-mounted in the `scraper` service so admin
  edits persist to the host.
- `refresh-accessible` deferred — not load-bearing yet.

### Phase 5 — Postgres write path ⏳ (next session)

**Blocked on:** user-supplied schema for rate cells / competitors.

- `scraper/db/connection.py` already in place (Phase 3). Extend with
  `writer.py` (takes a snapshot dict, writes to tables) and
  `models.py`.
- Schema lives in `db/migrations/` (hand-rolled SQL for now; Alembic
  later if views multiply).
- `snapshot.py` dual-writes to DB when `WRITE_DB=1` (env flag already
  wired into `docker-compose.yml`). JSON stays on as parity during
  cutover, then becomes the archive format.
- `run_job.py` migrates from `fcntl.flock` to Postgres advisory locks
  once the DB is authoritative.
- Extend Metabase dashboards with rate-trend tiles once data lands.

### Phase 6 — Metabase dashboards ✅ / Jobs API ⏳

- `metabase/provision.py` — idempotent bootstrap that runs Metabase's
  first-time setup (admin + Postgres connection) or re-auths if
  already set up, then creates/updates cards and lays out two
  dashboards via the REST API.
- Dashboard "Active scrapes" — scalar count + per-job progress table
  from `active_scrapes` view.
- Dashboard "Scrape history" — jobs-by-state pie, completed-by-OTA
  bar, per-day stacked line, and 100-row history table.
- Still deferred: FastAPI `POST /jobs` sidecar that shells to
  `run_job.py`. Only worth building once Metabase (or another UI)
  needs to trigger runs programmatically.

## Verification recipe (after Phase 3)

1. `docker compose up -d` → all services healthy.
2. Wait for `scraper-login` to seed `session.json`.
3. Spot scrape one cell (one hotel, one date, LOS=1, 1 person, brand.com).
4. Fire three concurrent full-fleet jobs, one per month, `--refresh`.
5. Repeat step 4 with `--no-refresh` — warm path, ~2s/hotel, same schema.
6. `output/locks/` empty after jobs finish.
7. Inspect one snapshot: `job_id`, `ota`, `los`, `persons` match flags.

After Phase 5:

8. Re-run with `-e WRITE_DB=1`; row counts in Postgres match JSON.

## Open items

- **Phase 5 schema from user** — the rate-cells / competitors /
  refreshes shape. Until it lands, snapshots stay as JSON.
- **Migrations tool** — hand-rolled SQL + a `migrate.sh` for now;
  consider Alembic once views multiply.
- **`hotels.json` editing UX** — Phase 4 CLI works for devs; a UI
  is a post-Phase-6 problem.
- **Jobs API** — deferred. Only worth building when Metabase (or
  another UI) needs to trigger runs programmatically.
- **Portfolio expansion 10 → 50+** — requires adding Lighthouse
  subscriptions (business/ops task), not code.

## Picking up tomorrow AM

1. **Bring the stack up** if it isn't already:
   ```
   cd /Users/user/Github/natsonhotels
   docker compose up -d
   ```
2. Confirm session is fresh (the login daemon should have kept it so):
   ```
   docker compose run --rm scraper python admin.py session
   ```
3. Live dashboards:
   - http://localhost:3010/dashboard/2#refresh=30 (Active scrapes)
   - http://localhost:3010/dashboard/3#refresh=60 (Scrape history)
4. **Phase 5 kickoff** — user shares rates-schema SQL, then:
   - drop the schema into `db/init/03_rates_schema.sql` (or a new
     `db/migrations/` dir if we pick Alembic)
   - implement `scraper/db/writer.py` using the shape
   - turn on `WRITE_DB=1` in `.env` and re-run a test scrape to see
     rows land alongside the JSON snapshot.
5. Once rates are in Postgres, extend the Metabase dashboards with
   rate-trend and parity tiles — `metabase/provision.py` is
   idempotent, so re-running it applies tile edits in place.

Branch state: on `refactor/dockerize-stack` with 7 commits since
`main`. Do NOT squash yet — each phase's commit message captures
context you'll want when reviewing.
