"""Trigger a Lighthouse rate refresh and poll until complete.

Uses the /apigateway/v1/app/liveshop endpoint to trigger Lighthouse's backend
to re-scrape all OTA sources for a hotel+month. Polls /api/v3/liveupdates/
until the job finishes (liveupdates array empties).

See api.md §4 "Rate Refresh (Live Shop)" for full endpoint documentation.
"""
import json
import sys
import time
from datetime import date, datetime, timezone

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
    """First and last day of YYYY-MM."""
    year, mo = map(int, month.split("-"))
    first = date(year, mo, 1)
    if mo == 12:
        last = date(year + 1, 1, 1)
    else:
        last = date(year, mo + 1, 1)
    from datetime import timedelta
    last = last - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def trigger_refresh(
    sess: requests.Session,
    hotel_id: str,
    month: str,
    compset_id: int = 1,
    los: int = 7,
    persons: int = 2,
    ota: str = "bookingdotcom",
) -> dict:
    """POST /liveshop to trigger a rate refresh for one hotel + one month.

    Returns the liveshop response dict on success, or raises on HTTP error.
    """
    from_date, to_date = _month_bounds(month)
    body = {
        "liveupdate": {
            "bulk_liveupdate_id": None,
            "completion_timestamp": None,
            "custom_range": False,
            "from_date": from_date,
            "to_date": to_date,
            "labels": "",
            "params": {
                "compset_ids": [compset_id],
                "los": los,
                "mealtype": 0,
                "membershiptype": 0,
                "persons": persons,
                "platform": -1,
                "roomtype": "all",
                "bar": True,
                "flexible": True,
                "rate_type": 0,
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
    """Poll /liveupdates until all jobs for this hotel finish.

    Returns True if all jobs completed within the timeout, False otherwise.
    """
    interval = poll_interval or REFRESH_POLL_INTERVAL_S
    timeout = poll_timeout or REFRESH_POLL_TIMEOUT_S
    start = time.time()

    while time.time() - start < timeout:
        r = sess.get(
            LIVEUPDATES_API,
            params={"hotel_id": hotel_id},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        jobs = data.get("liveupdates", [])

        if not jobs:
            return True

        # Check rate-limit flags.
        meta = data.get("meta", {})
        limits_hit = [k for k, v in meta.items() if v]
        if limits_hit:
            print(f"    [!] rate-limit flags active: {limits_hit}", flush=True)

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
    month: str,
    compset_id: int = 1,
    los: int = 7,
    persons: int = 2,
    ota: str = "bookingdotcom",
    poll_interval: int | None = None,
    poll_timeout: int | None = None,
) -> dict:
    """Trigger refresh for one hotel+month and block until complete.

    Returns {triggered_at, completed_at, duration_s, success, liveshop_response}.
    """
    triggered_at = datetime.now(timezone.utc)
    print(f"  [refresh] hotel={hotel_id} month={month} triggering...", flush=True)

    try:
        resp = trigger_refresh(sess, hotel_id, month, compset_id, los, persons, ota)
    except requests.HTTPError as e:
        print(f"  [refresh] trigger failed: {e}", flush=True)
        return {
            "triggered_at": triggered_at.isoformat(),
            "completed_at": None,
            "duration_s": None,
            "success": False,
            "error": str(e),
        }

    jobs = resp.get("liveupdates", [])
    if jobs:
        job = jobs[0]
        print(f"  [refresh] job id={job.get('id')} from={job.get('from_date')} to={job.get('to_date')} "
              f"days={job.get('nr_of_days')} status={job.get('status')}", flush=True)
    else:
        print("  [refresh] no job returned (may already be fresh)", flush=True)

    ok = poll_until_complete(sess, hotel_id, poll_interval, poll_timeout)
    completed_at = datetime.now(timezone.utc)
    duration = (completed_at - triggered_at).total_seconds()

    if ok:
        print(f"  [refresh] done in {duration:.0f}s", flush=True)
    else:
        print(f"  [refresh] timed out after {duration:.0f}s", flush=True)

    return {
        "triggered_at": triggered_at.isoformat(),
        "completed_at": completed_at.isoformat() if ok else None,
        "duration_s": round(duration, 1),
        "success": ok,
    }


if __name__ == "__main__":
    """Quick standalone test: refresh one hotel+month from the command line.

    Usage: python refresh.py <hotel_id> <month>
    Example: python refresh.py 276784 2026-06
    """
    if len(sys.argv) < 3:
        print("usage: python refresh.py <hotel_id> <month>")
        print("example: python refresh.py 276784 2026-06")
        sys.exit(2)

    from config import SESSION_FILE
    hotel_id = sys.argv[1]
    month = sys.argv[2]

    session_data = json.loads(SESSION_FILE.read_text())
    sess = requests.Session()
    for c in session_data["cookies"]:
        sess.cookies.set(c["name"], c["value"], domain=c["domain"])
    sess.headers.update({
        "User-Agent": session_data["user_agent"],
        "Accept": "application/json, text/plain, */*",
        "Origin": API_BASE,
    })

    result = refresh_and_wait(sess, hotel_id, month)
    print(json.dumps(result, indent=2))
