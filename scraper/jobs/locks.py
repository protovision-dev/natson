"""Per-(hotel_id, ota) advisory locks.

Prevents two concurrent scrape jobs from triggering refreshes on the
same (subscription, OTA) pair at the same time — Lighthouse has a
concurrency bucket for brand-shops and the UI-side rate-limit flag
(`limit_concurrent_subscription_high_prio_monthshop_brand`) fires
whenever you hit it.

Implementation: fcntl.flock on a per-pair file under output/locks/.
Flock is process-level; it scopes to the mounted volume, which is
shared across all `docker compose run` invocations on the same
session_vol, so independent scraper containers respect each other.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path


def _locks_dir(base: Path) -> Path:
    d = base / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextlib.contextmanager
def per_subscription_ota_lock(
    hotel_id: str,
    ota: str,
    output_dir: Path,
    timeout_s: float = 900.0,
    poll_s: float = 1.0,
):
    """Block until the (hotel_id, ota) lock is exclusively held.

    Raises TimeoutError if timeout_s elapses without acquiring the lock.
    The lock file is left behind on disk; only the fcntl advisory state
    matters, and release happens automatically on close().
    """
    path = _locks_dir(output_dir) / f"{hotel_id}_{ota}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    start = time.monotonic()
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as e:
                if time.monotonic() - start > timeout_s:
                    raise TimeoutError(
                        f"could not acquire lock for {hotel_id}/{ota} in {timeout_s:.0f}s"
                    ) from e
                time.sleep(poll_s)
        yield path
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
