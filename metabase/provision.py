"""Provision Metabase with a Postgres connection and two scrape dashboards.

Idempotent — running twice is safe:
  - First run: uses the Metabase setup-token to create the admin account,
    wire up Postgres, and build both dashboards.
  - Subsequent runs: authenticates, reuses any existing DB/cards/dashboards
    with matching names; creates anything missing.

Env needed (all from .env):
  METABASE_URL                 default http://metabase:3000 (inside stack)
                               or                http://localhost:3010 (host)
  METABASE_ADMIN_EMAIL / PASSWORD / FIRST_NAME / LAST_NAME
  POSTGRES_HOST / PORT / DB / USER / PASSWORD

Run from the host (Docker isn't required; only `requests` is):
  python3 metabase/provision.py

Or from inside the stack (scraper has requests installed):
  docker compose run --rm \
      -v "$PWD/metabase:/metabase" \
      -e METABASE_URL=http://metabase:3000 \
      scraper python /metabase/provision.py
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests


MB_URL = os.environ.get("METABASE_URL", "http://localhost:3010").rstrip("/")
ADMIN_EMAIL = os.environ.get("METABASE_ADMIN_EMAIL", "admin@natson.local")
ADMIN_PASSWORD = os.environ.get("METABASE_ADMIN_PASSWORD", "")
ADMIN_FIRST = os.environ.get("METABASE_ADMIN_FIRST_NAME", "Natson")
ADMIN_LAST = os.environ.get("METABASE_ADMIN_LAST_NAME", "Admin")

PG_HOST = os.environ.get("POSTGRES_HOST", "postgres")
PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
PG_DB = os.environ.get("POSTGRES_DB", "natson")
PG_USER = os.environ.get("POSTGRES_USER", "natson")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

SITE_NAME = "Natson Hotels"
DB_NAME_IN_METABASE = "Natson"


# -- tiny HTTP helpers -----------------------------------------------------

def _session(token: str | None = None) -> requests.Session:
    s = requests.Session()
    if token:
        s.headers["X-Metabase-Session"] = token
    s.headers["Content-Type"] = "application/json"
    return s


def _get(s: requests.Session, path: str) -> Any:
    r = s.get(f"{MB_URL}{path}", timeout=30)
    r.raise_for_status()
    return r.json() if r.content else None


def _post(s: requests.Session, path: str, body: dict) -> Any:
    r = s.post(f"{MB_URL}{path}", json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"POST {path} → {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else None


def _put(s: requests.Session, path: str, body: dict) -> Any:
    r = s.put(f"{MB_URL}{path}", json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"PUT {path} → {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else None


# -- setup / auth ----------------------------------------------------------

def wait_for_metabase(max_wait_s: int = 120) -> None:
    """Block until /api/health returns 200."""
    deadline = time.time() + max_wait_s
    while time.time() < deadline:
        try:
            r = requests.get(f"{MB_URL}/api/health", timeout=5)
            if r.ok and r.json().get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"Metabase at {MB_URL} did not come healthy in {max_wait_s}s")


def ensure_admin_and_db() -> tuple[str, int]:
    """Return (session_token, postgres_db_id_inside_metabase).

    First boot: uses the setup-token to create admin + Postgres connection.
    Later: authenticates with the admin creds and ensures the DB exists.
    """
    props = requests.get(f"{MB_URL}/api/session/properties", timeout=10).json()
    # Metabase keeps the setup-token value around even after the UI is set up;
    # the authoritative "has setup happened yet?" flag is `has-user-setup`.
    already_set_up = bool(props.get("has-user-setup"))
    setup_token = props.get("setup-token")

    if not already_set_up and setup_token:
        if not ADMIN_PASSWORD:
            raise RuntimeError("METABASE_ADMIN_PASSWORD not set — cannot run first-time setup")
        print(f"[mb] first-time setup (token present)")
        body = {
            "token": setup_token,
            "user": {
                "first_name": ADMIN_FIRST,
                "last_name": ADMIN_LAST,
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "site_name": SITE_NAME,
            },
            "prefs": {
                "site_name": SITE_NAME,
                "site_locale": "en",
                "allow_tracking": False,
            },
            "database": {
                "engine": "postgres",
                "name": DB_NAME_IN_METABASE,
                "details": {
                    "host": PG_HOST,
                    "port": PG_PORT,
                    "dbname": PG_DB,
                    "user": PG_USER,
                    "password": PG_PASSWORD,
                    "ssl": False,
                    "tunnel-enabled": False,
                },
                "is_on_demand": False,
                "is_full_sync": True,
            },
        }
        resp = requests.post(f"{MB_URL}/api/setup", json=body, timeout=60)
        resp.raise_for_status()
        token = resp.json()["id"]
    else:
        print(f"[mb] setup already done — authenticating as {ADMIN_EMAIL}")
        resp = requests.post(f"{MB_URL}/api/session", json={
            "username": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        }, timeout=30)
        if not resp.ok:
            raise RuntimeError(
                f"auth failed ({resp.status_code}): {resp.text[:300]}\n"
                f"Hint: if you've clicked through setup manually, set "
                f"METABASE_ADMIN_EMAIL/PASSWORD in .env to match."
            )
        token = resp.json()["id"]

    s = _session(token)

    # Locate our Postgres DB.
    dbs = _get(s, "/api/database")
    items = dbs.get("data", dbs) if isinstance(dbs, dict) else dbs
    db_id = None
    for d in items:
        details = d.get("details") or {}
        if d.get("engine") == "postgres" and details.get("dbname") == PG_DB:
            db_id = d["id"]
            break

    if db_id is None:
        print("[mb] adding Postgres connection")
        created = _post(s, "/api/database", {
            "engine": "postgres",
            "name": DB_NAME_IN_METABASE,
            "details": {
                "host": PG_HOST,
                "port": PG_PORT,
                "dbname": PG_DB,
                "user": PG_USER,
                "password": PG_PASSWORD,
                "ssl": False,
                "tunnel-enabled": False,
            },
            "is_full_sync": True,
        })
        db_id = created["id"]

    print(f"[mb] postgres db_id={db_id}")
    return token, db_id


# -- card + dashboard helpers ----------------------------------------------

def _find_by_name(s: requests.Session, path: str, name: str) -> dict | None:
    listing = _get(s, path)
    items = listing.get("data", listing) if isinstance(listing, dict) else listing
    for it in items:
        if it.get("name") == name:
            return it
    return None


def upsert_card(s: requests.Session, db_id: int, name: str, sql: str,
                display: str, visualization_settings: dict) -> int:
    body = {
        "name": name,
        "dataset_query": {
            "type": "native",
            "native": {"query": sql, "template-tags": {}},
            "database": db_id,
        },
        "display": display,
        "visualization_settings": visualization_settings,
        "database_id": db_id,
    }
    existing = _find_by_name(s, "/api/card", name)
    if existing:
        _put(s, f"/api/card/{existing['id']}", body)
        print(f"[mb] card updated: {name} (id={existing['id']})")
        return existing["id"]
    created = _post(s, "/api/card", body)
    print(f"[mb] card created: {name} (id={created['id']})")
    return created["id"]


def upsert_dashboard(s: requests.Session, name: str, description: str) -> int:
    existing = _find_by_name(s, "/api/dashboard", name)
    if existing:
        print(f"[mb] dashboard exists: {name} (id={existing['id']})")
        return existing["id"]
    created = _post(s, "/api/dashboard", {"name": name, "description": description})
    print(f"[mb] dashboard created: {name} (id={created['id']})")
    return created["id"]


def set_dashboard_cards(s: requests.Session, dashboard_id: int,
                        layout: list[dict]) -> None:
    """Replace the dashboard's card layout wholesale.

    layout items: {"card_id": N, "row": r, "col": c, "size_x": w, "size_y": h}
    """
    dashcards = []
    for idx, it in enumerate(layout):
        dashcards.append({
            "id": -(idx + 1),          # negative = new card
            "card_id": it["card_id"],
            "row": it["row"],
            "col": it["col"],
            "size_x": it["size_x"],
            "size_y": it["size_y"],
            "parameter_mappings": [],
            "visualization_settings": it.get("visualization_settings", {}),
        })
    _put(s, f"/api/dashboard/{dashboard_id}", {"dashcards": dashcards})
    print(f"[mb] dashboard {dashboard_id} laid out with {len(layout)} cards")


# -- actual dashboard definitions ------------------------------------------

ACTIVE_SQL_COUNT = "SELECT COUNT(*) AS active_jobs FROM active_scrapes"

ACTIVE_SQL_TABLE = """
SELECT
    job_id,
    state,
    ota,
    hotels_done || '/' || hotels_total AS progress,
    current_hotel,
    current_step,
    running_seconds,
    last_line
FROM active_scrapes
ORDER BY started_at DESC
""".strip()

RECENT_SQL_TABLE = """
SELECT
    job_id,
    state,
    ota,
    hotels_done || '/' || hotels_total AS progress,
    duration_seconds,
    do_refresh,
    refresh_only,
    checkin_from,
    checkin_to,
    exit_code,
    started_at
FROM recent_scrapes
LIMIT 100
""".strip()

RECENT_SQL_BY_STATE = """
SELECT state, COUNT(*)::int AS jobs
FROM scrape_jobs
GROUP BY state
ORDER BY jobs DESC
""".strip()

RECENT_SQL_BY_OTA = """
SELECT ota, COUNT(*)::int AS jobs
FROM scrape_jobs
WHERE state = 'completed' AND ota IS NOT NULL
GROUP BY ota
ORDER BY jobs DESC
""".strip()

RECENT_SQL_PER_DAY = """
SELECT
    DATE_TRUNC('day', started_at)::date AS day,
    COUNT(*)::int AS jobs
FROM scrape_jobs
GROUP BY 1
ORDER BY 1
""".strip()


# ---------- Rate intelligence cards (schema v3 facts) ----------

RATE_SQL_RECENT_CHANGES = """
SELECT
    observation_date,
    subject_code,
    source_code,
    competitor_name,
    stay_date,
    los,
    prior_rate_value,
    rate_value,
    rate_delta
FROM v_rate_trend
WHERE changed_from_prior = TRUE
  AND rate_delta IS NOT NULL
ORDER BY observation_date DESC, abs(rate_delta) DESC
LIMIT 100
""".strip()

RATE_SQL_BOOKING_CURVE = """
-- Booking curve: rate_value over observation_date, for each stay_date.
-- Filter to one subject + one source in Metabase to get a clean line.
SELECT
    observation_date,
    stay_date,
    source_code,
    subject_code,
    rate_value,
    all_in_price
FROM v_rate_trend
WHERE subject_code = 'ESA-AUS-LAKE'
  AND rate_value IS NOT NULL
ORDER BY stay_date, observation_date
""".strip()

RATE_SQL_VS_COMPSET = """
-- Own rate vs compset median across all future stay dates.
SELECT
    stay_date,
    subject_code,
    source_code,
    own_rate,
    median_rate,
    min_rate,
    max_rate,
    delta_vs_median,
    compset_size
FROM v_subject_vs_compset
ORDER BY subject_code, source_code, stay_date
""".strip()

RATE_SQL_COVERAGE = """
-- Compset coverage heatmap: how many competitors have a rate on each
-- stay_date for each subject, on today's scrape.
SELECT
    sh.internal_code        AS subject_code,
    ro.stay_date,
    COUNT(DISTINCT ro.competitor_hotel_pk) FILTER (WHERE ro.rate_value IS NOT NULL) AS competitors_with_rates
FROM rate_observations ro
JOIN subject_hotels sh USING (subject_hotel_id)
WHERE ro.observation_date = CURRENT_DATE
GROUP BY sh.internal_code, ro.stay_date
ORDER BY sh.internal_code, ro.stay_date
""".strip()

RATE_SQL_RUN_HEALTH = """
-- scrape_runs audit trail: per source per day, how many hotels
-- succeeded and how long the refresh totaled.
SELECT
    sr.scrape_date,
    s.source_code,
    sr.status,
    COUNT(srh.scrape_run_hotel_id) AS hotel_runs,
    SUM(srh.rates_count)::INT      AS total_rates,
    ROUND(AVG(srh.duration_s), 1)  AS avg_refresh_s
FROM scrape_runs sr
JOIN sources s ON s.source_id = sr.source_id
LEFT JOIN scrape_run_hotels srh USING (scrape_run_id)
GROUP BY sr.scrape_date, s.source_code, sr.status
ORDER BY sr.scrape_date DESC, s.source_code
""".strip()


def build_dashboards(s: requests.Session, db_id: int) -> None:
    # --- Active ---
    c_count = upsert_card(
        s, db_id, "Active scrape count", ACTIVE_SQL_COUNT,
        display="scalar",
        visualization_settings={"scalar.field": "active_jobs"},
    )
    c_active_tbl = upsert_card(
        s, db_id, "Active scrapes — detail", ACTIVE_SQL_TABLE,
        display="table",
        visualization_settings={},
    )

    active_id = upsert_dashboard(
        s, "Active scrapes",
        "Live view of jobs currently running. Open with #refresh=30 in the URL "
        "for automatic 30-second polling (already baked into the link printed "
        "by provision.py)."
    )
    set_dashboard_cards(s, active_id, [
        {"card_id": c_count,      "row": 0, "col": 0,  "size_x": 4,  "size_y": 3},
        {"card_id": c_active_tbl, "row": 0, "col": 4,  "size_x": 14, "size_y": 8},
    ])

    # --- History ---
    c_by_state = upsert_card(
        s, db_id, "Scrape jobs by state", RECENT_SQL_BY_STATE,
        display="pie",
        visualization_settings={
            "pie.dimension": "state",
            "pie.metric": "jobs",
        },
    )
    c_by_ota = upsert_card(
        s, db_id, "Completed scrapes by OTA", RECENT_SQL_BY_OTA,
        display="bar",
        visualization_settings={
            "graph.dimensions": ["ota"],
            "graph.metrics": ["jobs"],
        },
    )
    c_per_day = upsert_card(
        s, db_id, "Scrapes per day", RECENT_SQL_PER_DAY,
        display="line",
        visualization_settings={
            "graph.dimensions": ["day"],
            "graph.metrics": ["jobs"],
        },
    )
    c_recent_tbl = upsert_card(
        s, db_id, "Recent scrapes (last 100)", RECENT_SQL_TABLE,
        display="table",
        visualization_settings={},
    )

    hist_id = upsert_dashboard(
        s, "Scrape history",
        "Volume, durations, and outcomes over time. "
        "Combine with 'Active scrapes' for a full operational picture. "
        "Open with #refresh=60 in the URL to poll every minute."
    )
    set_dashboard_cards(s, hist_id, [
        {"card_id": c_by_state,    "row": 0,  "col": 0,  "size_x": 6,  "size_y": 6},
        {"card_id": c_by_ota,      "row": 0,  "col": 6,  "size_x": 6,  "size_y": 6},
        {"card_id": c_per_day,     "row": 0,  "col": 12, "size_x": 12, "size_y": 6},
        {"card_id": c_recent_tbl,  "row": 6,  "col": 0,  "size_x": 24, "size_y": 8},
    ])

    # --- Rate intelligence (Phase 5: rates_current, rate_observations, views) ---
    c_changes = upsert_card(
        s, db_id, "Rate changes (last 100)", RATE_SQL_RECENT_CHANGES,
        display="table",
        visualization_settings={},
    )
    c_curve = upsert_card(
        s, db_id, "Booking curve — ESA Austin Lakeline",
        RATE_SQL_BOOKING_CURVE,
        display="line",
        visualization_settings={
            "graph.dimensions": ["observation_date", "stay_date"],
            "graph.metrics":    ["rate_value"],
        },
    )
    c_vs_compset = upsert_card(
        s, db_id, "Own rate vs compset median", RATE_SQL_VS_COMPSET,
        display="line",
        visualization_settings={
            "graph.dimensions": ["stay_date"],
            "graph.metrics":    ["own_rate", "median_rate"],
        },
    )
    c_coverage = upsert_card(
        s, db_id, "Compset coverage by subject × stay date (today)",
        RATE_SQL_COVERAGE,
        display="table",
        visualization_settings={},
    )
    c_run_health = upsert_card(
        s, db_id, "Scrape run health", RATE_SQL_RUN_HEALTH,
        display="table",
        visualization_settings={},
    )

    rate_id = upsert_dashboard(
        s, "Rate intelligence",
        "Rate data captured by the ingest pipeline.  Open with #refresh=300 "
        "in the URL to poll every 5 minutes (rate data changes slowly vs. job "
        "state). Filter cards by subject_code / source_code to drill down."
    )
    set_dashboard_cards(s, rate_id, [
        {"card_id": c_vs_compset,  "row": 0,  "col": 0,  "size_x": 12, "size_y": 7},
        {"card_id": c_curve,       "row": 0,  "col": 12, "size_x": 12, "size_y": 7},
        {"card_id": c_changes,     "row": 7,  "col": 0,  "size_x": 24, "size_y": 7},
        {"card_id": c_coverage,    "row": 14, "col": 0,  "size_x": 12, "size_y": 7},
        {"card_id": c_run_health,  "row": 14, "col": 12, "size_x": 12, "size_y": 7},
    ])

    # Print user-facing URLs relative to the host (3010 publishes the port).
    # #refresh=N tells Metabase to auto-poll every N seconds — so these
    # links are "live" dashboards, not a one-shot snapshot.
    host_url = MB_URL.replace("http://metabase:3000", "http://localhost:3010")
    print()
    print(f"[mb] Active scrapes (live, polls 30s)   → "
          f"{host_url}/dashboard/{active_id}#refresh=30")
    print(f"[mb] Scrape history (live, polls 60s)   → "
          f"{host_url}/dashboard/{hist_id}#refresh=60")
    print(f"[mb] Rate intelligence (polls 300s)     → "
          f"{host_url}/dashboard/{rate_id}#refresh=300")


def main() -> int:
    print(f"[mb] url={MB_URL}  admin={ADMIN_EMAIL}  pg_host={PG_HOST}  pg_db={PG_DB}")
    wait_for_metabase()
    token, db_id = ensure_admin_and_db()
    s = _session(token)
    build_dashboards(s, db_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[mb] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
