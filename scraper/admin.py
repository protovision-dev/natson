"""Portfolio admin CLI — manage hotels.json subscriptions.

Subcommands:
    list                       show all portfolio entries
    add    <id> <name...>      add one subscription
    remove <id>                remove one subscription
    session                    show session.json age + TTL remaining

Run inside the scraper container:
    docker compose run --rm scraper python admin.py list
    docker compose run --rm scraper python admin.py add 409987 "New Studio 6"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jobs.hotels import (
    add_subscription, remove_subscription, _load as _load_hotels_cfg,
)
from login import session_age_s, SESSION_TTL_S
from config import SESSION_FILE


def cmd_list(_args) -> int:
    cfg = _load_hotels_cfg()
    hotels = cfg.get("hotels", [])
    if not hotels:
        print("(no subscriptions)")
        return 0
    width = max(len(h["hotel_id"]) for h in hotels)
    print(f"{'HOTEL_ID':<{width}}  NAME")
    for h in hotels:
        print(f"{h['hotel_id']:<{width}}  {h['name']}")
    print(f"\ntotal: {len(hotels)}")
    return 0


def cmd_add(args) -> int:
    name = " ".join(args.name)
    add_subscription(args.hotel_id, name)
    print(f"[ok] added {args.hotel_id}  {name}")
    return 0


def cmd_remove(args) -> int:
    ok = remove_subscription(args.hotel_id)
    if ok:
        print(f"[ok] removed {args.hotel_id}")
        return 0
    print(f"[!] {args.hotel_id} not found")
    return 1


def cmd_session(_args) -> int:
    age = session_age_s(SESSION_FILE)
    if age is None:
        print("session.json: MISSING or unreadable")
        return 1
    remaining = SESSION_TTL_S - age
    status = "FRESH" if remaining > 7200 else ("EXPIRING SOON" if remaining > 0 else "EXPIRED")
    print(f"session.json: {status}")
    print(f"  age:       {age:.0f}s  ({age/3600:.1f}h)")
    print(f"  remaining: {remaining:.0f}s  ({remaining/3600:.1f}h)")
    print(f"  ttl:       {SESSION_TTL_S}s  ({SESSION_TTL_S/3600:.0f}h)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Portfolio + session admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List portfolio subscriptions")

    add = sub.add_parser("add", help="Add a subscription")
    add.add_argument("hotel_id")
    add.add_argument("name", nargs="+")

    rm = sub.add_parser("remove", help="Remove a subscription")
    rm.add_argument("hotel_id")

    sub.add_parser("session", help="Show session.json freshness")

    args = p.parse_args()
    return {"list": cmd_list, "add": cmd_add, "remove": cmd_remove,
            "session": cmd_session}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
