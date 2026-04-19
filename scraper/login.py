"""Log into MyLighthouse via the local browser-api and save a reusable cookie jar.

Callable as a script (for manual use) or a library (for login_daemon.py).

Requires the browser-api service to be running.  In docker-compose,
BROWSER_API defaults to http://browser-api:8765 (the compose service
name).  On the host, set BROWSER_API=http://localhost:8765.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

from config import BROWSER_API, SESSION_FILE

SESSION_TTL_S = int(os.environ.get("SESSION_TTL_S", "86400"))  # 24h per api.md


def _build_payload(username: str, password: str) -> dict:
    return {
        "url": "https://app.mylighthouse.com/",
        "viewport": {"width": 1440, "height": 900},
        "initialWaitUntil": "networkidle",
        "steps": [
            {"action": "waitForSelector", "selector": "input[type=email]", "timeout": 30000},
            {"action": "fill", "selector": "input[type=email]", "value": username},
            {"action": "press", "selector": "input[type=email]", "key": "Enter"},
            {"action": "waitForSelector", "selector": "input[type=password]", "timeout": 15000},
            {"action": "fill", "selector": "input[type=password]", "value": password},
            {"action": "press", "selector": "input[type=password]", "key": "Enter"},
            {
                "action": "waitForResponse",
                "urlContains": "/api/v3/users/?only_self=true",
                "status": 200,
                "timeout": 45000,
            },
        ],
        "cookieDomains": ["app.mylighthouse.com"],
        "cookieNames": ["sessionid", "csrftoken"],
    }


def login(
    username: str | None = None, password: str | None = None, out_path: Path | None = None
) -> dict:
    """Perform the browser-api login flow and write session.json.

    Returns the session payload (same shape as the file).
    Raises RuntimeError on failure.
    """
    username = username or os.environ.get("LH_USER")
    password = password or os.environ.get("LH_PASS")
    if not username or not password:
        raise RuntimeError("LH_USER / LH_PASS not set (check .env)")

    out_path = out_path or SESSION_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    r = requests.post(f"{BROWSER_API}/login", json=_build_payload(username, password), timeout=180)
    r.raise_for_status()
    resp = r.json()
    if not resp.get("success"):
        raise RuntimeError(f"login failed: {resp.get('error')}")

    payload = {
        "user_agent": resp["userAgent"],
        "cookies": [
            {"name": c["name"], "value": c["value"], "domain": c["domain"]} for c in resp["cookies"]
        ],
        "logged_in_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "session_ttl_s": SESSION_TTL_S,
        "final_url": resp.get("finalUrl"),
    }
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


def session_age_s(path: Path | None = None) -> float | None:
    """Seconds since logged_in_at; None if the file is missing or unreadable."""
    p = path or SESSION_FILE
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    ts = data.get("logged_in_at")
    if not ts:
        return None
    try:
        when = datetime.fromisoformat(ts)
    except Exception:
        return None
    return (datetime.now(UTC) - when).total_seconds()


if __name__ == "__main__":
    try:
        data = login()
    except Exception as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)
    print(
        f"[*] wrote {SESSION_FILE} ({[c['name'] for c in data['cookies']]}) "
        f"— finalUrl={data.get('final_url')}"
    )
