"""Daily snapshot storage — write and read per-hotel JSON snapshots.

Writes to output/snapshots/{YYYY-MM-DD}/{hotel_id}.json.
This module is the adapter layer that will grow a Postgres backend in Phase 3.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

from config import SNAPSHOTS_DIR


def _day_dir(scrape_date: str | date | None = None) -> Path:
    if scrape_date is None:
        scrape_date = date.today().isoformat()
    elif isinstance(scrape_date, date):
        scrape_date = scrape_date.isoformat()
    d = SNAPSHOTS_DIR / scrape_date
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_hotel_snapshot(hotel_id: str, data: dict,
                        scrape_date: str | date | None = None,
                        ota_suffix: str = "") -> Path:
    """Write one hotel's daily snapshot to disk. Returns the file path.

    ota_suffix (e.g. "_branddotcom") keeps parallel scrapes from colliding.
    """
    d = _day_dir(scrape_date)
    p = d / f"{hotel_id}{ota_suffix}.json"
    p.write_text(json.dumps(data, indent=2, default=str))
    return p


def save_daily_summary(results: list[dict],
                       started_at: str | None = None,
                       scrape_date: str | date | None = None,
                       ota_suffix: str = "") -> Path:
    """Write the daily summary index."""
    d = _day_dir(scrape_date)
    summary = {
        "scrape_date": d.name,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "hotels_scraped": sum(1 for r in results if r.get("status") == "ok"),
        "hotels_failed": sum(1 for r in results if r.get("status") != "ok"),
        "results": results,
    }
    p = d / f"summary{ota_suffix}.json"
    p.write_text(json.dumps(summary, indent=2, default=str))
    return p


def load_hotel_snapshot(hotel_id: str,
                        scrape_date: str | date | None = None,
                        ota_suffix: str = "") -> dict | None:
    d = _day_dir(scrape_date)
    p = d / f"{hotel_id}{ota_suffix}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def list_snapshot_dates() -> list[str]:
    """Return sorted list of YYYY-MM-DD strings for which snapshots exist."""
    if not SNAPSHOTS_DIR.exists():
        return []
    return sorted(
        d.name for d in SNAPSHOTS_DIR.iterdir()
        if d.is_dir() and len(d.name) == 10
    )
