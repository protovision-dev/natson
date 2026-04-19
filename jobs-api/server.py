"""Thin FastAPI wrapper around scraper/run_job.py.

The Next.js web service POSTs to /jobs to trigger a scrape; the sidecar
spawns `python run_job.py …` as a subprocess (job_id pre-generated so
the response can return it immediately) and returns. Status updates are
already written to:
  - Postgres `scrape_jobs` table (every state transition)
  - `output/jobs/<job_id>/status.json` + `run.log`

We don't tail those here — the web service polls Postgres directly via
the existing views (`active_scrapes`, `recent_scrapes`).

Concurrency: capped by MAX_PARALLEL_JOBS env (counted by inspecting our
own active children; 429 if the cap is hit).
"""
from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

OUT_DIR = Path(os.environ.get("OUT_DIR", "/app/output"))
RUN_JOB_PY = Path(os.environ.get("RUN_JOB_PY", "/app/run_job.py"))
SCRAPER_CWD = Path(os.environ.get("SCRAPER_CWD", "/app"))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_JOBS", "2"))

app = FastAPI(title="natson-jobs-api", version="0.1.0")

# Track subprocess.Popen handles so we can count active jobs.
_active: dict[str, subprocess.Popen] = {}


class JobRequest(BaseModel):
    hotels: list[str] = Field(..., min_length=1, description="Subscription IDs")
    dates: str = Field(..., description="YYYY-MM | YYYY-MM-DD | rolling:N | range:start:end")
    ota: Literal["bookingdotcom", "branddotcom"] = "bookingdotcom"
    los: int | None = Field(None, ge=1, le=90)
    persons: int | None = Field(None, ge=1, le=10)
    refresh: bool = True


class JobResponse(BaseModel):
    job_id: str
    pid: int
    started_at: str


def _new_job_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def _purge_finished() -> None:
    """Reap any subprocess.Popen handles whose process has exited."""
    finished = [jid for jid, p in _active.items() if p.poll() is not None]
    for jid in finished:
        _active.pop(jid, None)


@app.get("/health")
def health() -> dict:
    _purge_finished()
    return {
        "ok": True,
        "active_jobs": len(_active),
        "max_parallel": MAX_PARALLEL,
        "run_job_py": str(RUN_JOB_PY),
        "out_dir": str(OUT_DIR),
    }


@app.post("/jobs", response_model=JobResponse, status_code=202)
def create_job(req: JobRequest) -> JobResponse:
    _purge_finished()
    if len(_active) >= MAX_PARALLEL:
        raise HTTPException(
            status_code=429,
            detail=f"Max parallel jobs reached ({MAX_PARALLEL}). Try again shortly.",
        )

    if not RUN_JOB_PY.exists():
        raise HTTPException(status_code=500, detail=f"run_job.py not found at {RUN_JOB_PY}")

    # Validate hotel IDs are numeric strings (subscription IDs).
    for h in req.hotels:
        if not h.isdigit():
            raise HTTPException(status_code=400, detail=f"hotel id must be numeric: {h!r}")

    job_id = _new_job_id()
    cmd = [
        "python", str(RUN_JOB_PY),
        "--hotels", ",".join(req.hotels),
        "--dates", req.dates,
        "--ota", req.ota,
        "--job-id", job_id,
    ]
    if req.los is not None:
        cmd += ["--los", str(req.los)]
    if req.persons is not None:
        cmd += ["--persons", str(req.persons)]
    cmd += ["--refresh"] if req.refresh else ["--no-refresh"]

    # Spawn detached from the request lifetime. stdout/stderr are tee'd
    # by run_job.py itself into output/jobs/<id>/run.log, so we redirect
    # to DEVNULL here to avoid filling our buffer.
    proc = subprocess.Popen(
        cmd,
        cwd=str(SCRAPER_CWD),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _active[job_id] = proc

    return JobResponse(
        job_id=job_id,
        pid=proc.pid,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


@app.get("/jobs/{job_id}/status")
def job_status(job_id: str) -> dict:
    """Read the per-job status.json written by scraper/jobs/status.py."""
    status_path = OUT_DIR / "jobs" / job_id / "status.json"
    if not status_path.exists():
        raise HTTPException(status_code=404, detail=f"no status for {job_id}")
    import json
    try:
        data = json.loads(status_path.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"unreadable status.json: {e}")
    proc = _active.get(job_id)
    data["alive"] = proc is not None and proc.poll() is None
    return data
