"""Trigger a Lighthouse rate refresh and poll until complete.

Uses the /apigateway/v1/app/liveshop endpoint to trigger Lighthouse's backend
to re-scrape all OTA sources for a hotel+date-window (≤31 days per POST).
Polls /api/v3/liveupdates/ until the job finishes.

See api.md §4 "Rate Refresh (Live Shop)" for full endpoint documentation.
"""
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

from config import (
    LIVEUPDATES_API,
    API_BASE,
    POLITE_SLEEP,
    REFRESH_POLL_INTERVAL_S,
    REFRESH_POLL_TIMEOUT_S,
)

LIVESHOP_API = f"{API_BASE}/apigateway/v1/app/liveshop"


def _month_bounds(month: str) -> tuple[str, str]:
    year, mo = map(int, month.split("-"))
    first = date(year, mo, 1)
    last = (date(year + 1, 1, 1) if mo == 12 else date(year, mo + 1, 1)) - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def trigger_refresh(
    sess: requests.Session,
    hotel_id: str,
    from_date: date | str,
    to_date: date | str,
    *,
    ota: str = "bookingdotcom",
    compset_id: int = 1,
    los: int = 7,
    persons: int = 2,
    mealtype: int = 0,
    membershiptype: int = 0,
    platform: int = -1,
    roomtype: str = "all",
    bar: bool = True,
    flexible: bool = True,
    rate_type: int = 0,
) -> dict:
    """POST /liveshop to trigger a rate refresh for one hotel + one window.

    Window must be ≤31 days (Lighthouse API limit).  Raises on HTTP error.
    """
    fd = from_date.isoformat() if isinstance(from_date, date) else from_date
    td = to_date.isoformat() if isinstance(to_date, date) else to_date

    body = {
        "liveupdate": {
            "bulk_liveupdate_id": None,
            "completion_timestamp": None,
            "custom_range": False,
            "from_date": fd,
            "to_date": td,
            "labels": "",
            "params": {
                "compset_ids": [compset_id],
                "los": los,
                "mealtype": mealtype,
                "membershiptype": membershiptype,
                "persons": persons,
                "platform": platform,
                "roomtype": roomtype,
                "bar": bool(bar),
                "flexible": bool(flexible),
                "rate_type": rate_type,
            },
            "priority": 0,
            "send_email": False,
            "start_timestamp": None,
            "status": None,
            "type": "rates",
            "hotel": str(hotel_id),
            "ota": ota,
        }
    }
    csrftoken = sess.cookies.get("csrftoken", domain="app.mylighthouse.com") or ""
    r = sess.post(
        LIVESHOP_API,
        params={"subscription_id": hotel_id},
        json=body,
        headers={
            "X-CSRFToken": csrftoken,
            "Referer": f"{API_BASE}/hotel/{hotel_id}/rates",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def poll_until_complete(
    sess: requests.Session,
    hotel_id: str,
    poll_interval: int | None = None,
    poll_timeout: int | None = None,
) -> bool:
    """Poll /liveupdates until all jobs for this hotel finish."""
    interval = poll_interval or REFRESH_POLL_INTERVAL_S
    timeout = poll_timeout or REFRESH_POLL_TIMEOUT_S
    start = time.time()

    while time.time() - start < timeout:
        r = sess.get(LIVEUPDATES_API, params={"hotel_id": hotel_id}, timeout=30)
        r.raise_for_status()
        data = r.json()
        jobs = data.get("liveupdates", [])

        if not jobs:
            return True

        active = [j for j in jobs if j.get("completion_timestamp") in (None, "", "null")]
        if not active:
            return True

        elapsed = int(time.time() - start)
        print(f"    polling... {len(active)} active job(s), {elapsed}s elapsed", flush=True)
        time.sleep(interval)

    return False


def refresh_and_wait(
    sess: requests.Session,
    hotel_id: str,
    from_date: date | str,
    to_date: date | str,
    *,
    ota: str = "bookingdotcom",
    compset_id: int = 1,
    los: int = 7,
    persons: int = 2,
    mealtype: int = 0,
    membershiptype: int = 0,
    platform: int = -1,
    roomtype: str = "all",
    bar: bool = True,
    flexible: bool = True,
    rate_type: int = 0,
    poll_interval: int | None = None,
    poll_timeout: int | None = None,
) -> dict:
    """Trigger refresh for one hotel + window and block until complete.

    Returns {triggered_at, completed_at, duration_s, success, from, to}.
    """
    fd = from_date.isoformat() if isinstance(from_date, date) else from_date
    td = to_date.isoformat() if isinstance(to_date, date) else to_date

    triggered_at = datetime.now(timezone.utc)
    print(f"  [refresh] hotel={hotel_id} ota={ota} from={fd} to={td} triggering...", flush=True)

    try:
        resp = trigger_refresh(
            sess, hotel_id, fd, td,
            ota=ota, compset_id=compset_id, los=los, persons=persons,
            mealtype=mealtype, membershiptype=membershiptype, platform=platform,
            roomtype=roomtype, bar=bar, flexible=flexible, rate_type=rate_type,
        )
    except requests.HTTPError as e:
        print(f"  [refresh] trigger failed: {e}", flush=True)
        return {
            "triggered_at": triggered_at.isoformat(),
            "completed_at": None,
            "duration_s": None,
            "success": False,
            "from": fd, "to": td,
            "error": str(e),
        }

    jobs = resp.get("liveupdates", [])
    if jobs:
        job = jobs[0]
        print(f"  [refresh] job id={job.get('id')} from={job.get('from_date')} "
              f"to={job.get('to_date')} days={job.get('nr_of_days')} "
              f"status={job.get('status')}", flush=True)
    else:
        print("  [refresh] no job returned (may already be fresh)", flush=True)

    ok = poll_until_complete(sess, hotel_id, poll_interval, poll_timeout)
    completed_at = datetime.now(timezone.utc)
    duration = (completed_at - triggered_at).total_seconds()

    print(f"  [refresh] {'done' if ok else 'timed out'} in {duration:.0f}s", flush=True)
    return {
        "triggered_at": triggered_at.isoformat(),
        "completed_at": completed_at.isoformat() if ok else None,
        "duration_s": round(duration, 1),
        "success": ok,
        "from": fd, "to": td,
    }


if __name__ == "__main__":
    """Standalone: refresh one hotel + one month.

    Usage: python refresh.py <hotel_id> <month>  (e.g. 276784 2026-06)
    """
    if len(sys.argv) < 3:
        print("usage: python refresh.py <hotel_id> <month>")
        sys.exit(2)

    from config import SESSION_FILE
    hotel_id = sys.argv[1]
    month = sys.argv[2]
    fd, td = _month_bounds(month)

    s_data = json.loads(SESSION_FILE.read_text())
    sess = requests.Session()
    for c in s_data["cookies"]:
        sess.cookies.set(c["name"], c["value"], domain=c["domain"])
    sess.headers.update({
        "User-Agent": s_data["user_agent"],
        "Accept": "application/json, text/plain, */*",
        "Origin": API_BASE,
    })

    print(json.dumps(refresh_and_wait(sess, hotel_id, fd, td), indent=2))
