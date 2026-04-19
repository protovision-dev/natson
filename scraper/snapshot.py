"""Per-job snapshot storage.

Writes to output/snapshots/{YYYY-MM-DD}/{hotel_id}_{ota}_{job_id}.json,
plus a per-job summary at output/snapshots/{YYYY-MM-DD}/summary_{job_id}.json.

The legacy `{hotel_id}[_{ota_suffix}].json` filename is still supported
for callers that don't supply a job_id (e.g. one-off standalone usage).

This is also the dual-write point for Postgres (Phase 5).  JSON is
written first and is authoritative; if the DB is configured and
WRITE_DB != "0", we then call `db.ingest_snapshot()`.  A DB failure is
logged but never raised — the scrape always succeeds as long as the
JSON lands.
"""

import json
import logging
import os
from datetime import UTC, date, datetime
from pathlib import Path

from config import SNAPSHOTS_DIR

_log = logging.getLogger(__name__)


def _day_dir(scrape_date: str | date | None = None) -> Path:
    if scrape_date is None:
        scrape_date = date.today().isoformat()
    elif isinstance(scrape_date, date):
        scrape_date = scrape_date.isoformat()
    d = SNAPSHOTS_DIR / scrape_date
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshot_filename(
    hotel_id: str, *, job_id: str | None, ota: str | None, ota_suffix: str
) -> str:
    if job_id:
        ota_part = f"_{ota}" if ota else ""
        return f"{hotel_id}{ota_part}_{job_id}.json"
    return f"{hotel_id}{ota_suffix}.json"


def save_hotel_snapshot(
    hotel_id: str,
    data: dict,
    scrape_date: str | date | None = None,
    *,
    job_id: str | None = None,
    ota: str | None = None,
    ota_suffix: str = "",
) -> Path:
    """Write one hotel's snapshot to disk. Returns the file path.

    Also dual-writes to Postgres via db.ingest_snapshot() when
    configured.  JSON is authoritative; DB failures are logged, never
    raised.
    """
    d = _day_dir(scrape_date)
    p = d / _snapshot_filename(hotel_id, job_id=job_id, ota=ota, ota_suffix=ota_suffix)
    p.write_text(json.dumps(data, indent=2, default=str))

    if os.environ.get("WRITE_DB", "1") != "0" and job_id:
        try:
            from db import ingest_snapshot, pg_configured  # lazy import

            if pg_configured():
                ingest_snapshot(data, job_id=job_id)
        except Exception as e:
            _log.warning("DB ingest skipped (%s: %s)", type(e).__name__, e)

    return p


def save_job_summary(job, results: list[dict], scrape_date: str | date | None = None) -> Path:
    """Write a summary index for one Job. Returns the file path."""
    d = _day_dir(scrape_date)
    payload = {
        "scrape_date": d.name,
        "job_id": job.job_id,
        "started_at": job.created_at,
        "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "hotels_scraped": sum(1 for r in results if r.get("status") == "ok"),
        "hotels_failed": sum(1 for r in results if r.get("status") != "ok"),
        "spec": job.to_dict(),
        "results": results,
    }
    p = d / f"summary_{job.job_id}.json"
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


# --- Legacy helpers kept for one-off CLIs and Phase-2 compatibility ------


def save_daily_summary(
    results: list[dict],
    started_at: str | None = None,
    scrape_date: str | date | None = None,
    ota_suffix: str = "",
) -> Path:
    d = _day_dir(scrape_date)
    summary = {
        "scrape_date": d.name,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "hotels_scraped": sum(1 for r in results if r.get("status") == "ok"),
        "hotels_failed": sum(1 for r in results if r.get("status") != "ok"),
        "results": results,
    }
    p = d / f"summary{ota_suffix}.json"
    p.write_text(json.dumps(summary, indent=2, default=str))
    return p


def load_hotel_snapshot(
    hotel_id: str, scrape_date: str | date | None = None, ota_suffix: str = ""
) -> dict | None:
    d = _day_dir(scrape_date)
    p = d / f"{hotel_id}{ota_suffix}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def list_snapshot_dates() -> list[str]:
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(d.name for d in SNAPSHOTS_DIR.iterdir() if d.is_dir() and len(d.name) == 10)
