"""Backfill Postgres from on-disk snapshot JSONs.

Walks scraper/output/snapshots/{date}/ and hands each snapshot dict
to db.ingest_snapshot().  Use this to:

  - Populate a fresh Postgres from historical JSON snapshots.
  - Re-ingest after fixing a schema/ingest bug.
  - Heal a gap where WRITE_DB was off for a few runs.

Ingest is idempotent on the rate_observations natural key
(source, subject, competitor, stay_date, LOS, persons, observation_date),
so re-running is safe.

Usage:
    python reconcile.py --date 2026-04-17
    python reconcile.py --date 2026-04-17 --hotel 345062
    python reconcile.py --date 2026-04-17 --ota branddotcom
    python reconcile.py --since 2026-04-16 --until 2026-04-18
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from config import SNAPSHOTS_DIR
from db import ingest_snapshot, pg_configured


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _snapshots_for_day(day: date) -> list[Path]:
    d = SNAPSHOTS_DIR / day.isoformat()
    if not d.exists():
        return []
    # Skip summary_*.json files.
    return sorted(
        p for p in d.iterdir() if p.suffix == ".json" and not p.name.startswith("summary")
    )


def _matches(snap: dict, hotel: str | None, ota: str | None) -> bool:
    if hotel and str(snap.get("hotel_id")) != str(hotel):
        return False
    if ota and snap.get("ota") != ota:
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest on-disk JSON snapshots into Postgres.")
    p.add_argument("--date", help="single YYYY-MM-DD scrape date")
    p.add_argument("--since", help="start of range YYYY-MM-DD (inclusive)")
    p.add_argument("--until", help="end of range YYYY-MM-DD (inclusive, default=today)")
    p.add_argument("--hotel", help="filter to this subscription_id")
    p.add_argument("--ota", help="filter to this OTA (e.g. bookingdotcom)")
    p.add_argument(
        "--dry-run", action="store_true", help="show what would be ingested; don't call ingest"
    )
    args = p.parse_args()

    if not pg_configured() and not args.dry_run:
        print("[!] Postgres not configured — set POSTGRES_* env (or --dry-run)", file=sys.stderr)
        return 2

    if args.date:
        start = end = date.fromisoformat(args.date)
    elif args.since:
        start = date.fromisoformat(args.since)
        end = date.fromisoformat(args.until) if args.until else date.today()
    else:
        print("[!] --date or --since required", file=sys.stderr)
        return 2

    total_files = 0
    total_ok = 0
    total_skip = 0
    total_fail = 0

    for day in _daterange(start, end):
        for path in _snapshots_for_day(day):
            try:
                snap = json.loads(path.read_text())
            except Exception as e:
                print(f"[!] skip {path.name}: {e}")
                continue

            if not _matches(snap, args.hotel, args.ota):
                total_skip += 1
                continue

            total_files += 1
            label = f"{day.isoformat()}  {path.name:<60}"
            if args.dry_run:
                print(f"[would-ingest] {label}")
                continue

            job_id = snap.get("job_id") or f"reconcile-{day.isoformat()}-{path.stem}"
            try:
                run_id = ingest_snapshot(snap, job_id=job_id)
            except Exception as e:
                total_fail += 1
                print(f"[FAIL] {label}  {type(e).__name__}: {e}")
                continue

            if run_id is None:
                total_fail += 1
                print(f"[FAIL] {label}  (ingest returned None — see scraper logs)")
            else:
                total_ok += 1
                print(f"[ok]   {label}  scrape_run_id={run_id}")

    print()
    print(
        f"[*] files matched: {total_files}  ok: {total_ok}  failed: {total_fail}  "
        f"filtered out: {total_skip}"
    )
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
