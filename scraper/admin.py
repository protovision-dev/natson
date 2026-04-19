"""Portfolio admin CLI — manage hotels.json subscriptions + subject metadata.

Subcommands:
    list                        show all portfolio entries (hotels.json)
    list-subjects               show subject_hotels (richer metadata)
    add <id> <name...>          add one subscription (prompts for subject fields)
    remove <id>                 remove one subscription
    session                     show session.json age + TTL remaining
    close-compset-member <subject_internal_code> <competitor_external_hotel_id>
                                set valid_to=CURRENT_DATE on an active compset row

Run inside the scraper container:
    docker compose run --rm scraper python admin.py list
    docker compose run --rm scraper python admin.py add 409987 "New Studio 6"
    docker compose run --rm scraper python admin.py close-compset-member S6-WPB 183310
"""

from __future__ import annotations

import argparse
import json
import sys

from config import SCRAPER_DIR, SESSION_FILE
from jobs.hotels import (
    _load as _load_hotels_cfg,
)
from jobs.hotels import (
    add_subscription,
    remove_subscription,
)
from login import SESSION_TTL_S, session_age_s

SUBJECT_FILE = SCRAPER_DIR / "subject_hotels.json"


# ---- subject_hotels.json helpers --------------------------------------


def _load_subjects() -> dict:
    if not SUBJECT_FILE.exists():
        return {"subjects": []}
    return json.loads(SUBJECT_FILE.read_text())


def _save_subjects(data: dict) -> None:
    SUBJECT_FILE.write_text(json.dumps(data, indent=2) + "\n")


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {label}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


# ---- command handlers -------------------------------------------------


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


def cmd_list_subjects(_args) -> int:
    data = _load_subjects()
    subjects = data.get("subjects", [])
    if not subjects:
        print("(no subject metadata yet)")
        return 0
    fmt = "{hid:<8}  {code:<14}  {display:<40}  {brand:<25}  {city:<18}  {st:<4}  cs={cs}"
    print(
        fmt.format(
            hid="HOTEL_ID",
            code="CODE",
            display="DISPLAY_NAME",
            brand="BRAND",
            city="CITY",
            st="ST",
            cs="CS",
        )
    )
    for s in subjects:
        print(
            fmt.format(
                hid=s["hotel_id"],
                code=s["internal_code"],
                display=s["display_name"][:40],
                brand=s.get("brand", "")[:25],
                city=(s.get("city") or "")[:18],
                st=s.get("state") or "",
                cs=s.get("lighthouse_compset_id"),
            )
        )
    print(f"\ntotal: {len(subjects)}")
    return 0


def cmd_add(args) -> int:
    # 1) hotels.json (Job-facing subscription list)
    name = " ".join(args.name)
    add_subscription(args.hotel_id, name)
    print(f"[ok] added {args.hotel_id}  {name} (hotels.json)")

    # 2) subject_hotels.json (richer metadata for the DB)
    print("\nAlso capturing richer subject metadata for the DB.")
    print("Press Enter to skip; you can fill these in later by editing the file.")
    internal_code = _prompt("internal_code (e.g. S6-WPB)", default=f"HID-{args.hotel_id}")
    display_name = _prompt("display_name", default=name[:40])
    city = _prompt("city")
    state = _prompt("state (2-letter)")
    country = _prompt("country", default="US")
    brand = _prompt("brand")
    compset_id = _prompt("lighthouse_compset_id", default="1")

    data = _load_subjects()
    subjects = data.setdefault("subjects", [])
    subjects = [s for s in subjects if s.get("hotel_id") != args.hotel_id]
    subjects.append(
        {
            "hotel_id": args.hotel_id,
            "internal_code": internal_code,
            "display_name": display_name,
            "city": city or None,
            "state": state or None,
            "country": country or None,
            "brand": brand or None,
            "lighthouse_compset_id": int(compset_id) if compset_id else None,
        }
    )
    data["subjects"] = subjects
    _save_subjects(data)
    print(
        "[ok] wrote subject_hotels.json  (remember to re-run db/migrate.sh"
        " if the DB is already live; new subjects need seed SQL)"
    )
    return 0


def cmd_remove(args) -> int:
    ok = remove_subscription(args.hotel_id)
    if ok:
        print(f"[ok] removed {args.hotel_id} from hotels.json")
    else:
        print(f"[!] {args.hotel_id} not in hotels.json")

    data = _load_subjects()
    before = len(data.get("subjects", []))
    data["subjects"] = [s for s in data.get("subjects", []) if s.get("hotel_id") != args.hotel_id]
    if len(data["subjects"]) != before:
        _save_subjects(data)
        print(f"[ok] removed {args.hotel_id} from subject_hotels.json")
    return 0 if ok else 1


def cmd_session(_args) -> int:
    age = session_age_s(SESSION_FILE)
    if age is None:
        print("session.json: MISSING or unreadable")
        return 1
    remaining = SESSION_TTL_S - age
    status = "FRESH" if remaining > 7200 else ("EXPIRING SOON" if remaining > 0 else "EXPIRED")
    print(f"session.json: {status}")
    print(f"  age:       {age:.0f}s  ({age / 3600:.1f}h)")
    print(f"  remaining: {remaining:.0f}s  ({remaining / 3600:.1f}h)")
    print(f"  ttl:       {SESSION_TTL_S}s  ({SESSION_TTL_S / 3600:.0f}h)")
    return 0


def cmd_close_compset_member(args) -> int:
    try:
        from db import get_conn, pg_configured
    except Exception as e:
        print(f"[!] can't import db module: {e}")
        return 1
    if not pg_configured():
        print("[!] Postgres not configured — set POSTGRES_* env vars")
        return 1
    conn = get_conn()
    if conn is None:
        print("[!] Postgres unreachable")
        return 1

    sql = """
    UPDATE compset_members cm
       SET valid_to = CURRENT_DATE
      FROM subject_hotels s
      JOIN hotels h  ON h.hotel_pk = s.hotel_pk
      JOIN hotels ch ON ch.external_hotel_id = %s
     WHERE cm.subject_hotel_id    = s.subject_hotel_id
       AND cm.competitor_hotel_pk = ch.hotel_pk
       AND cm.valid_to IS NULL
       AND s.internal_code = %s
    RETURNING cm.compset_member_id, s.internal_code, ch.external_hotel_id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (args.competitor_id, args.subject_code))
        rows = cur.fetchall()
    if not rows:
        print(
            f"[!] no active compset_members row matched "
            f"({args.subject_code}, competitor external_hotel_id={args.competitor_id})"
        )
        return 1
    for cm_id, code, ext in rows:
        print(f"[ok] closed compset_member_id={cm_id}  subject={code}  competitor={ext}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Portfolio + session admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List portfolio subscriptions (hotels.json)")
    sub.add_parser("list-subjects", help="List subject metadata (subject_hotels.json)")

    add = sub.add_parser("add", help="Add a subscription (prompts for subject fields)")
    add.add_argument("hotel_id")
    add.add_argument("name", nargs="+")

    rm = sub.add_parser("remove", help="Remove a subscription from both files")
    rm.add_argument("hotel_id")

    sub.add_parser("session", help="Show session.json freshness")

    ccm = sub.add_parser(
        "close-compset-member", help="Set valid_to=CURRENT_DATE on an active compset row"
    )
    ccm.add_argument("subject_code", help="subject_hotels.internal_code (e.g. S6-WPB)")
    ccm.add_argument("competitor_id", help="competitor external_hotel_id (Lighthouse hotelinfo_id)")

    args = p.parse_args()
    return {
        "list": cmd_list,
        "list-subjects": cmd_list_subjects,
        "add": cmd_add,
        "remove": cmd_remove,
        "session": cmd_session,
        "close-compset-member": cmd_close_compset_member,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
