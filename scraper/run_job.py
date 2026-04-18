"""CLI entrypoint: one scrape job per invocation.

Every tunable parameter is exposed as a flag; anything left unset falls
back to scraper.config.yml.  Within a job, hotels are iterated
sequentially with per-(hotel, ota) locks so that multiple `docker
compose run --rm scraper run_job.py ...` invocations can run in
parallel without contending on Lighthouse's refresh concurrency.

See roadmap.md and jobs/spec.py for the full flag surface.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from config import OUT_DIR, SESSION_FILE, CACHE_DIR
from jobs.spec import Job, add_cli_args
from jobs.locks import per_subscription_ota_lock
from jobs.status import StatusWriter, log_path
from scrape import make_session, scrape_hotel, Caches
from snapshot import save_hotel_snapshot, save_job_summary

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "scraper.config.yml"


def _config() -> dict:
    return yaml.safe_load(_CONFIG_PATH.read_text())


# ---------- cache I/O ----------

HOTELS_CACHE = CACHE_DIR / "hotels.json"
HOTELINFOS_CACHE = CACHE_DIR / "hotelinfos.json"


def _booking_urls_cache_path(ota: str) -> Path:
    # /redirect returns OTA-specific URLs; keep caches segregated.
    suffix = "" if ota == "bookingdotcom" else f"_{ota}"
    return CACHE_DIR / f"booking_base_urls{suffix}.json"


def _load(path: Path, refresh: bool) -> dict:
    if refresh or not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str, sort_keys=True))


# ---------- stdout tee to per-job log ----------

class _Tee:
    """Mirror stdout writes to a log file so `monitor.py tail` can follow."""
    def __init__(self, stream, fh):
        self._stream = stream
        self._fh = fh

    def write(self, s):
        self._stream.write(s)
        try:
            self._fh.write(s)
            self._fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        self._stream.flush()
        try:
            self._fh.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


# ---------- main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a single Lighthouse scrape job (one per invocation)."
    )
    add_cli_args(parser)
    parser.add_argument("--from-spec", dest="from_spec", default=None,
        help="Load a Job from a JSON spec instead of CLI flags.")
    args, _ = parser.parse_known_args()

    if args.from_spec:
        job = Job.from_file(Path(args.from_spec))
    else:
        job = Job.from_cli(args)

    if not SESSION_FILE.exists():
        print(f"[!] {SESSION_FILE} missing — run login_daemon.py (or login.py) first",
              file=sys.stderr)
        return 2

    cfg = _config()
    jitter_h = cfg["pacing"]["jitter_hotels_s"]
    jitter_m = cfg["pacing"]["jitter_months_s"]  # unused for now; kept for future
    lock_timeout = float(cfg["locks"]["lock_timeout_s"])

    # Reproducibility: write the resolved spec before doing any work.
    spec_path = job.write(OUT_DIR)

    # Tee stdout/stderr to a per-job log so monitor.py tail can follow.
    log_file = open(log_path(OUT_DIR, job.job_id), "a", buffering=1)
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)

    status = StatusWriter(OUT_DIR, job.job_id, job.to_dict())
    status.set(state="running")

    header = (f"[*] job={job.job_id}  hotels={len(job.hotels)}  "
              f"dates={job.checkin_dates[0]}..{job.checkin_dates[-1]} "
              f"({len(job.checkin_dates)} days)  ota={job.ota}  "
              f"refresh={'ON' if job.do_refresh else 'OFF'}"
              f"{'  (refresh-only)' if job.refresh_only else ''}")
    print(header)
    print(f"[*] spec written to {spec_path}")
    status.log_line(header)

    sess = make_session()

    # Refresh-meta env flag: bust the hotels/hotelinfos/urls caches selectively.
    refresh_meta = os.environ.get("REFRESH_META", "").lower()
    refresh_all = refresh_meta in ("1", "true", "yes", "all")
    hotels_cache = _load(HOTELS_CACHE, refresh_all or "hotels" in refresh_meta)
    hotelinfos_cache = _load(HOTELINFOS_CACHE, refresh_all or "hotelinfos" in refresh_meta)
    booking_urls_path = _booking_urls_cache_path(job.ota)
    booking_cache = _load(booking_urls_path, refresh_all or "urls" in refresh_meta)
    caches = Caches(hotels=hotels_cache, hotelinfos=hotelinfos_cache,
                    booking_urls=booking_cache)

    summary_results = []
    for i, hotel_id in enumerate(job.hotels, 1):
        banner = f"[{i}/{len(job.hotels)}] hotel_id={hotel_id}"
        print(f"\n{'='*60}")
        print(banner)
        status.set(current={"hotel_id": hotel_id, "index": i, "total": len(job.hotels), "step": "starting"})
        status.log_line(banner)

        t0 = time.time()
        try:
            with per_subscription_ota_lock(
                hotel_id, job.ota, OUT_DIR, timeout_s=lock_timeout,
            ):
                status.set(current={"hotel_id": hotel_id, "index": i, "total": len(job.hotels), "step": "scraping"})
                snap = scrape_hotel(sess, job, hotel_id, caches)
                path = save_hotel_snapshot(hotel_id, snap, job_id=job.job_id, ota=job.ota)
            dur = time.time() - t0
            ok_line = f"  [ok] {snap.get('total_rate_cells', 0)} rate cells → {path.name} ({dur:.0f}s)"
            print(ok_line)
            status.log_line(ok_line)
            status.mark_hotel_done(ok=True)
            summary_results.append({
                "hotel_id": hotel_id, "status": "ok",
                "duration_s": round(dur, 1),
                "rates_count": snap.get("total_rate_cells", 0),
                "snapshot": path.name,
            })
        except Exception as e:
            dur = time.time() - t0
            fail_line = f"  [FAIL] {type(e).__name__}: {e}"
            print(fail_line)
            status.log_line(fail_line)
            status.mark_hotel_done(ok=False)
            summary_results.append({
                "hotel_id": hotel_id, "status": "failed",
                "duration_s": round(dur, 1),
                "error": f"{type(e).__name__}: {e}",
            })

        if i < len(job.hotels):
            jitter = random.uniform(float(jitter_h[0]), float(jitter_h[1]))
            print(f"  (waiting {jitter:.1f}s before next hotel)")
            time.sleep(jitter)

    _save(HOTELS_CACHE, caches.hotels)
    _save(HOTELINFOS_CACHE, caches.hotelinfos)
    _save(booking_urls_path, caches.booking_urls)

    summary_path = save_job_summary(job, summary_results)
    ok = sum(1 for r in summary_results if r["status"] == "ok")
    done_line = f"\n[*] {ok}/{len(summary_results)} hotels scraped → {summary_path}"
    print(done_line)
    status.log_line(done_line)
    exit_code = 0 if ok == len(summary_results) else 1
    status.finish(exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
