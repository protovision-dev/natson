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

Auth: defense-in-depth even though the sidecar isn't published to the
host. POST /jobs requires `X-Internal-Auth: $JOBS_API_INTERNAL_TOKEN`.
GET /health stays open for compose healthchecks.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

OUT_DIR = Path(os.environ.get("OUT_DIR", "/app/output"))
RUN_JOB_PY = Path(os.environ.get("RUN_JOB_PY", "/app/run_job.py"))
SCRAPER_CWD = Path(os.environ.get("SCRAPER_CWD", "/app"))
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_JOBS", "2"))
INTERNAL_TOKEN = os.environ.get("JOBS_API_INTERNAL_TOKEN", "")

# Allowed --dates forms (mirrors scraper/jobs/dates.py parser):
#   2026-04-25         single date
#   2026-04            month
#   2026-04:2026-06    month range
#   2026-04-01:2026-04-30   date range
#   rolling:N          current month + next N
_DATES_RE = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}(:\d{4}-\d{2}-\d{2})?"
    r"|\d{4}-\d{2}(:\d{4}-\d{2})?"
    r"|rolling:\d{1,3}"
    r")$"
)

app = FastAPI(title="natson-jobs-api", version="0.2.0")

# Track subprocess.Popen handles so we can count active jobs.
_active: dict[str, subprocess.Popen] = {}


def _check_internal_auth(token: str | None) -> None:
    """Constant-time compare against JOBS_API_INTERNAL_TOKEN.

    If the env token is unset the sidecar refuses every protected call —
    safer than silently allowing all traffic in a misconfigured deploy.
    """
    if not INTERNAL_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="JOBS_API_INTERNAL_TOKEN not configured on the sidecar",
        )
    if not token or not secrets.compare_digest(token, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="invalid internal token")


class JobRequest(BaseModel):
    hotels: list[str] = Field(..., min_length=1, description="Subscription IDs")
    dates: str = Field(
        ...,
        description="YYYY-MM-DD | YYYY-MM | YYYY-MM:YYYY-MM | "
        "YYYY-MM-DD:YYYY-MM-DD | rolling:N",
    )
    ota: Literal["bookingdotcom", "branddotcom"] = "bookingdotcom"
    los: int | None = Field(None, ge=1, le=90)
    persons: int | None = Field(None, ge=1, le=10)
    refresh: bool = True

    @field_validator("hotels")
    @classmethod
    def _hotels_numeric(cls, v: list[str]) -> list[str]:
        for h in v:
            if not h.isdigit():
                raise ValueError(f"hotel id must be numeric: {h!r}")
        return v

    @field_validator("dates")
    @classmethod
    def _dates_well_formed(cls, v: str) -> str:
        if not _DATES_RE.match(v):
            raise ValueError(
                "dates must match YYYY-MM-DD | YYYY-MM | YYYY-MM:YYYY-MM | "
                "YYYY-MM-DD:YYYY-MM-DD | rolling:N"
            )
        return v


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
        "auth_configured": bool(INTERNAL_TOKEN),
        "run_job_py": str(RUN_JOB_PY),
        "out_dir": str(OUT_DIR),
    }


@app.post("/jobs", response_model=JobResponse, status_code=202)
def create_job(
    req: JobRequest,
    x_internal_auth: str | None = Header(default=None, alias="X-Internal-Auth"),
) -> JobResponse:
    _check_internal_auth(x_internal_auth)
    _purge_finished()

    if len(_active) >= MAX_PARALLEL:
        raise HTTPException(
            status_code=429,
            detail=f"Max parallel jobs reached ({MAX_PARALLEL}). Try again shortly.",
        )

    if not RUN_JOB_PY.exists():
        raise HTTPException(status_code=500, detail=f"run_job.py not found at {RUN_JOB_PY}")

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
def job_status(
    job_id: str,
    x_internal_auth: str | None = Header(default=None, alias="X-Internal-Auth"),
) -> dict:
    """Read the per-job status.json written by scraper/jobs/status.py."""
    _check_internal_auth(x_internal_auth)
    status_path = OUT_DIR / "jobs" / job_id / "status.json"
    if not status_path.exists():
        raise HTTPException(status_code=404, detail=f"no status for {job_id}")
    try:
        data = json.loads(status_path.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"unreadable status.json: {e}") from e
    proc = _active.get(job_id)
    data["alive"] = proc is not None and proc.poll() is None
    return data
