"""Scrape-active lock files.

Each running scrape writes `output/locks/active/{job_id}.lock` with JSON
metadata (job_id, hotels, date range, started_at).  The login daemon
inspects this directory before re-logging in: if any non-stale active
lock exists and the session still has some TTL left, it defers the
relogin so the in-flight scrape keeps using its in-memory cookies.

Stale detection: a lock file whose mtime is older than
LOCK_STALE_AFTER_S (default 2h) is treated as abandoned — it almost
certainly belongs to a crashed scrape that never got to remove it.
The stale threshold is the also-generous upper bound for how long any
one scrape job should take (current portfolio runs are 30-60 min).

The daemon still has a "panic" floor: if remaining TTL drops below
PANIC_TTL_S (default 300s), it relogins anyway — a dead session is
worse than a freshly-refreshed one mid-scrape.

Lock-filename convention is `{job_id}.lock` so the file is human-
readable and traceable to a specific Job; multiple concurrent scrapes
each get their own file (no refcounting needed).
"""
from __future__ import annotations

import json
import os
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def locks_dir(out_dir: Path) -> Path:
    d = out_dir / "locks" / "active"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ScrapeLock(AbstractContextManager):
    """Context manager that writes a lock file for the life of a scrape.

    Usage:
        with ScrapeLock(OUT_DIR, job.job_id, {...}):
            # run the scrape
    Removes the file on normal exit AND on exception.
    """

    def __init__(self, out_dir: Path, job_id: str, meta: dict | None = None):
        self.path = locks_dir(out_dir) / f"{job_id}.lock"
        self.meta = {
            "job_id":     job_id,
            "pid":        os.getpid(),
            "started_at": _now_iso(),
            **(meta or {}),
        }

    def __enter__(self):
        self.path.write_text(json.dumps(self.meta, indent=2, default=str))
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass
        return False   # don't swallow exceptions


def active_scrapes(out_dir: Path, stale_after_s: float = 7200.0) -> list[dict]:
    """Return metadata for each live scrape.  Files older than
    `stale_after_s` are ignored — a crashed scrape that never cleaned up
    shouldn't block daemon refreshes forever."""
    d = locks_dir(out_dir)
    now = time.time()
    out: list[dict] = []
    for f in d.iterdir():
        if not f.is_file() or f.suffix != ".lock":
            continue
        try:
            age = now - f.stat().st_mtime
        except OSError:
            continue
        if age > stale_after_s:
            continue
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            # unreadable — still treat as active to be safe, log nothing here
            out.append({"job_id": f.stem, "started_at": "unknown"})
    return out
