"""Keep session.json fresh.

Runs as the `scraper-login` service in docker-compose.  Every
LOGIN_CHECK_INTERVAL_S seconds, reads session.json's logged_in_at
field and re-logs in if the age is within LOGIN_MARGIN_S of the
session TTL (or if the file is missing / unreadable).

Tunable via env:
    LOGIN_CHECK_INTERVAL_S   default 900   (15 min)
    LOGIN_MARGIN_S           default 7200  (relogin when <2h left)
    SESSION_TTL_S            default 86400 (24h, set in login.py)
"""
from __future__ import annotations

import os
import random
import sys
import time
from datetime import datetime, timezone

from login import login, session_age_s, SESSION_TTL_S
from config import SESSION_FILE

CHECK_INTERVAL_S = int(os.environ.get("LOGIN_CHECK_INTERVAL_S", "900"))
MARGIN_S = int(os.environ.get("LOGIN_MARGIN_S", "7200"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def needs_relogin() -> tuple[bool, str]:
    """Return (should_relogin, reason_for_log)."""
    age = session_age_s(SESSION_FILE)
    if age is None:
        return True, "session.json missing or unreadable"
    remaining = SESSION_TTL_S - age
    if remaining < MARGIN_S:
        return True, f"age={age:.0f}s, remaining={remaining:.0f}s (<{MARGIN_S}s margin)"
    return False, f"age={age:.0f}s, remaining={remaining:.0f}s"


def main() -> int:
    print(f"[{_now()}] login_daemon starting "
          f"(interval={CHECK_INTERVAL_S}s, margin={MARGIN_S}s, "
          f"ttl={SESSION_TTL_S}s)", flush=True)

    while True:
        should, reason = needs_relogin()
        if should:
            print(f"[{_now()}] relogin triggered: {reason}", flush=True)
            try:
                login()
                print(f"[{_now()}] relogin OK; session written to {SESSION_FILE}",
                      flush=True)
            except Exception as e:
                print(f"[{_now()}] relogin FAILED: {type(e).__name__}: {e}",
                      flush=True, file=sys.stderr)
                # Back off briefly; next tick retries.
                time.sleep(60)
                continue
        else:
            print(f"[{_now()}] session fresh — {reason}", flush=True)

        # Sleep with a small jitter so multiple daemons (unusual but possible)
        # don't hammer in lockstep.
        jitter = random.uniform(-30, 30)
        time.sleep(max(60, CHECK_INTERVAL_S + jitter))


if __name__ == "__main__":
    sys.exit(main())
