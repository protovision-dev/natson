"""Keep session.json fresh.

Runs as the `scraper-login` service in docker-compose.  Every
LOGIN_CHECK_INTERVAL_S seconds, reads session.json's logged_in_at
field and re-logs in if the age is within LOGIN_MARGIN_S of the
session TTL (or if the file is missing / unreadable).

Deferral logic (added in the session-lock fix):
    - If ANY active scrape lock exists under output/locks/active/, the
      daemon DEFERS re-login so the in-flight scrape keeps working
      against its in-memory cookies.
    - Locks older than LOCK_STALE_AFTER_S are treated as dead and
      ignored (a crashed scrape shouldn't block the daemon forever).
    - PANIC_TTL_S floor: if remaining TTL drops below this threshold,
      re-login anyway — a dead session is worse than a freshly-
      refreshed one mid-scrape.

Tunable via env:
    LOGIN_CHECK_INTERVAL_S   default 900   (15 min)
    LOGIN_MARGIN_S           default 7200  (relogin when <2h left)
    SESSION_TTL_S            default 86400 (24h, set in login.py)
    LOCK_STALE_AFTER_S       default 7200  (2h — abandoned lock threshold)
    PANIC_TTL_S              default 300   (5 min — force relogin floor)
"""

from __future__ import annotations

import os
import random
import sys
import time
from datetime import UTC, datetime

from config import OUT_DIR, SESSION_FILE
from jobs.scrape_lock import active_scrapes
from login import SESSION_TTL_S, login, session_age_s

CHECK_INTERVAL_S = int(os.environ.get("LOGIN_CHECK_INTERVAL_S", "900"))
MARGIN_S = int(os.environ.get("LOGIN_MARGIN_S", "7200"))
LOCK_STALE_AFTER_S = int(os.environ.get("LOCK_STALE_AFTER_S", "7200"))
PANIC_TTL_S = int(os.environ.get("PANIC_TTL_S", "300"))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def needs_relogin() -> tuple[bool, str]:
    """Return (should_relogin, reason_for_log).

    Priority:
        1. Panic: remaining < PANIC_TTL_S  → always relogin (session about
           to die organically).
        2. Defer: remaining < MARGIN_S but active scrape(s) present
           → skip; report deferral reason.
        3. Normal: remaining < MARGIN_S   → relogin.
        4. Fresh: remaining ≥ MARGIN_S    → no action.
    """
    age = session_age_s(SESSION_FILE)
    if age is None:
        # No session at all — nothing to defer; start from scratch.
        return True, "session.json missing or unreadable"

    remaining = SESSION_TTL_S - age

    if remaining < PANIC_TTL_S:
        return True, (
            f"PANIC: {remaining:.0f}s left (<{PANIC_TTL_S}s) "
            f"— forcing relogin even if scrapes are active"
        )

    if remaining < MARGIN_S:
        scrapes = active_scrapes(OUT_DIR, stale_after_s=LOCK_STALE_AFTER_S)
        if scrapes:
            ids = ", ".join(s.get("job_id", "?") for s in scrapes)
            return False, (
                f"defer: {len(scrapes)} active scrape(s) [{ids}]; remaining={remaining:.0f}s"
            )
        return True, f"age={age:.0f}s, remaining={remaining:.0f}s (<{MARGIN_S}s margin)"

    return False, f"age={age:.0f}s, remaining={remaining:.0f}s"


def main() -> int:
    print(
        f"[{_now()}] login_daemon starting "
        f"(interval={CHECK_INTERVAL_S}s, margin={MARGIN_S}s, "
        f"ttl={SESSION_TTL_S}s, panic={PANIC_TTL_S}s, "
        f"stale={LOCK_STALE_AFTER_S}s)",
        flush=True,
    )

    while True:
        should, reason = needs_relogin()
        if should:
            print(f"[{_now()}] relogin triggered: {reason}", flush=True)
            try:
                login()
                print(f"[{_now()}] relogin OK; session written to {SESSION_FILE}", flush=True)
            except Exception as e:
                print(
                    f"[{_now()}] relogin FAILED: {type(e).__name__}: {e}",
                    flush=True,
                    file=sys.stderr,
                )
                # Back off briefly; next tick retries.
                time.sleep(60)
                continue
        else:
            print(f"[{_now()}] {reason}", flush=True)

        # Sleep with a small jitter so multiple daemons (unusual but possible)
        # don't hammer in lockstep.
        jitter = random.uniform(-30, 30)
        time.sleep(max(60, CHECK_INTERVAL_S + jitter))


if __name__ == "__main__":
    sys.exit(main())
