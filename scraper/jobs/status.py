"""Per-job status writing — a small filesystem-backed state machine.

Writes to `output/jobs/{job_id}/status.json` as a job progresses.  The
monitor CLI reads these files to show live progress across every
running and recently-finished job without needing a database.

Shape:
    {
      "job_id": "...",
      "state": "starting" | "running" | "completed" | "failed",
      "started_at": "2026-04-18T00:45:12Z",
      "updated_at": "2026-04-18T00:47:01Z",
      "completed_at": null | "2026-04-18T00:52:33Z",
      "pid": 12345,
      "hotels_total": 10,
      "hotels_done": 3,
      "hotels_failed": 0,
      "current": {"hotel_id": "276780", "step": "refresh:2026-05", ...} | null,
      "spec": {...},       # minimal copy of the Job
      "last_line": "...",  # last log line (for at-a-glance)
      "exit_code": null | 0 | 1 | ...
    }
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _job_dir(out_dir: Path, job_id: str) -> Path:
    d = out_dir / "jobs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def status_path(out_dir: Path, job_id: str) -> Path:
    return _job_dir(out_dir, job_id) / "status.json"


def log_path(out_dir: Path, job_id: str) -> Path:
    return _job_dir(out_dir, job_id) / "run.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_status(out_dir: Path, payload: dict) -> None:
    """Atomically write status.json — overwrite-in-place via rename."""
    p = status_path(out_dir, payload["job_id"])
    payload = {**payload, "updated_at": _now()}
    fd, tmp = tempfile.mkstemp(prefix=".status.", dir=p.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read_status(out_dir: Path, job_id: str) -> dict | None:
    p = status_path(out_dir, job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def list_jobs(out_dir: Path) -> list[dict]:
    """Every job with a status.json on disk, sorted newest-first by job_id."""
    root = out_dir / "jobs"
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        s = read_status(out_dir, d.name)
        if s:
            out.append(s)
    return out


class StatusWriter:
    """Convenience wrapper — caches the payload so updates are one-liners."""

    def __init__(self, out_dir: Path, job_id: str, spec: dict):
        self.out_dir = out_dir
        self.payload: dict[str, Any] = {
            "job_id": job_id,
            "state": "starting",
            "started_at": _now(),
            "completed_at": None,
            "pid": os.getpid(),
            "hotels_total": len(spec.get("hotels", [])),
            "hotels_done": 0,
            "hotels_failed": 0,
            "current": None,
            "spec": spec,
            "last_line": "",
            "exit_code": None,
        }
        self.flush()

    def set(self, **fields) -> None:
        self.payload.update(fields)
        self.flush()

    def log_line(self, line: str) -> None:
        """Remember the most recent human-readable log line."""
        self.payload["last_line"] = line.strip()
        self.flush()

    def mark_hotel_done(self, ok: bool) -> None:
        if ok:
            self.payload["hotels_done"] += 1
        else:
            self.payload["hotels_failed"] += 1
        self.flush()

    def finish(self, exit_code: int) -> None:
        self.payload["state"] = "completed" if exit_code == 0 else "failed"
        self.payload["completed_at"] = _now()
        self.payload["exit_code"] = exit_code
        self.payload["current"] = None
        self.flush()

    def flush(self) -> None:
        write_status(self.out_dir, self.payload)
        # Mirror to Postgres so Metabase can render active/recent scrapes.
        # Import lazily so the scraper still works with no Postgres at all.
        try:
            from db.jobs import upsert_job_status
            upsert_job_status(self.payload)
        except Exception:
            pass
