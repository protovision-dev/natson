# Natson Hotels — Lighthouse Scraper → Production Stack

Living spec for turning the Lighthouse rate scraper into a small enterprise
BI app: fully containerized, flexible job-driven scraping, concurrent runs,
Postgres persistence, Metabase visualization.

## Current state (2026-04-17)

- 10 portfolio hotels ("subscriptions" in Lighthouse terms) — only these
  can drive `/rates/` and `/liveshop` calls. The 71 "accessible" hotels in
  `scraper/output/accessible_hotels.json` appear as compset competitors
  inside portfolio scrapes; they are read-only siblings, not independently
  driveable.
- Working daily workflow: `login.py` → `scrape.py` (with or without
  refresh), writes JSON snapshots to
  `scraper/output/snapshots/{date}/{hotel_id}[_{ota}].json`.
- `browser-api/` service handles login (Camoufox in Docker on port 8765).
  Everything else uses session cookies + plain HTTP.
- Two OTAs proven: `bookingdotcom` (7,007 cells) and `branddotcom`
  (7,735 cells) both captured cleanly today.

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

### Phase 2 — Root compose + Postgres + Metabase scaffold

- `docker-compose.yml` at repo root with services: `browser-api`,
  `scraper`, `scraper-login`, `postgres` (16), `metabase`.
- `scraper/Dockerfile` (python:3.12-slim, sleep infinity default CMD).
- `scraper/requirements.txt` pinned.
- `.env.example` at root (Postgres + Metabase creds, Lighthouse user/pass).
- Named volumes: `pg_data`, `metabase_data`, `session_vol`,
  `scraper_output`.
- `db/init/00_extensions.sql` placeholder.

### Phase 3 — Config file + Job abstraction + `run_job` CLI + Metabase-visible job state

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

### Phase 5 — Postgres write path

- `scraper/db/{connection,writer,models}.py`.
- Schema (user-supplied) goes in `db/migrations/`.
- `snapshot.py` dual-writes to DB when `WRITE_DB=1`.
- `run_job.py` migrates from flock to Postgres advisory locks.

### Phase 6 — Metabase dashboards + optional Jobs API

- Starter `metabase/dashboards.json`.
- Optional FastAPI sidecar (`scraper/api/server.py`) with
  `POST /jobs` → shells to `run_job.py` — deferred until Metabase
  needs to trigger runs.

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

- Metabase's own state DB: separate DB inside the main Postgres
  instance (recommended) vs internal H2.
- Migrations tool: hand-rolled SQL + `migrate.sh` for now; Alembic
  later once views multiply.
- Who edits `hotels.json` long-term? Phase 4 CLI is fine for devs; a
  UI is a Phase 6+ problem.
