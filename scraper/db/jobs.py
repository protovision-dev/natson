"""scrape_jobs upsert — one row per Job, updated on every state transition.

Table defined in db/init/02_scrape_jobs.sql.  Used by run_job.py.
"""
from __future__ import annotations

import json
import socket

from .connection import get_conn


_UPSERT_SQL = """
INSERT INTO scrape_jobs (
    job_id, state,
    started_at, updated_at, completed_at,
    pid, host,
    hotels_total, hotels_done, hotels_failed,
    current_hotel, current_step,
    ota, checkin_from, checkin_to, do_refresh, refresh_only,
    last_line, exit_code, spec
) VALUES (
    %(job_id)s, %(state)s,
    %(started_at)s, %(updated_at)s, %(completed_at)s,
    %(pid)s, %(host)s,
    %(hotels_total)s, %(hotels_done)s, %(hotels_failed)s,
    %(current_hotel)s, %(current_step)s,
    %(ota)s, %(checkin_from)s, %(checkin_to)s, %(do_refresh)s, %(refresh_only)s,
    %(last_line)s, %(exit_code)s, %(spec)s
)
ON CONFLICT (job_id) DO UPDATE SET
    state         = EXCLUDED.state,
    updated_at    = EXCLUDED.updated_at,
    completed_at  = COALESCE(EXCLUDED.completed_at, scrape_jobs.completed_at),
    hotels_done   = EXCLUDED.hotels_done,
    hotels_failed = EXCLUDED.hotels_failed,
    current_hotel = EXCLUDED.current_hotel,
    current_step  = EXCLUDED.current_step,
    last_line     = EXCLUDED.last_line,
    exit_code     = COALESCE(EXCLUDED.exit_code, scrape_jobs.exit_code)
;
"""


def upsert_job_status(payload: dict) -> bool:
    """Write or update one row.  Returns True on success, False on noop/fail.

    Accepts the same dict the filesystem StatusWriter maintains.  Only the
    fields we store in the table are read; extras are ignored.
    """
    conn = get_conn()
    if conn is None:
        return False

    spec = payload.get("spec") or {}
    checkins = spec.get("checkin_dates") or []
    row = {
        "job_id":        payload["job_id"],
        "state":         payload["state"],
        "started_at":    payload.get("started_at"),
        "updated_at":    payload.get("updated_at") or payload.get("started_at"),
        "completed_at":  payload.get("completed_at"),
        "pid":           payload.get("pid"),
        "host":          socket.gethostname(),
        "hotels_total":  payload.get("hotels_total", 0),
        "hotels_done":   payload.get("hotels_done", 0),
        "hotels_failed": payload.get("hotels_failed", 0),
        "current_hotel": (payload.get("current") or {}).get("hotel_id"),
        "current_step":  (payload.get("current") or {}).get("step"),
        "ota":           spec.get("ota"),
        "checkin_from":  checkins[0]  if checkins else None,
        "checkin_to":    checkins[-1] if checkins else None,
        "do_refresh":    spec.get("do_refresh"),
        "refresh_only":  spec.get("refresh_only"),
        "last_line":     (payload.get("last_line") or "")[:500],
        "exit_code":     payload.get("exit_code"),
        "spec":          json.dumps(spec, default=str),
    }
    try:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, row)
        return True
    except Exception as e:
        # Don't let a DB hiccup kill a scrape — log and continue.
        print(f"[db] upsert_job_status failed: {type(e).__name__}: {e}")
        return False
