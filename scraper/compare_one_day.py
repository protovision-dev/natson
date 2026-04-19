"""Compare Lighthouse vs Booking.com for one property, one check-in date.

Scrapes all 10 competitors' Booking.com pages via browser-api (with proxy),
extracts the b_rooms_available_and_soldout blob, and compares the lowest
7-night price against Lighthouse's shop_value.

Usage: .venv/bin/python compare_one_day.py [hotel_id] [checkin_date]
Default: 345062 2026-05-01
"""

import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

API = os.environ.get("BROWSER_API", "http://localhost:8765")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "4"))
SNAPSHOT_DIR = Path("output/snapshots")

HOTEL_ID = sys.argv[1] if len(sys.argv) > 1 else "345062"
CHECKIN = sys.argv[2] if len(sys.argv) > 2 else "2026-05-01"
LOS = 7
CHECKOUT = (date.fromisoformat(CHECKIN) + timedelta(days=LOS)).isoformat()


def lock_dates(url, checkin, checkout):
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["checkin"] = checkin
    q["checkout"] = checkout
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def extract_room_blob(html):
    key = "b_rooms_available_and_soldout:"
    i = html.find(key)
    if i < 0:
        return None
    i += len(key)
    while i < len(html) and html[i] in " \t\n":
        i += 1
    if i >= len(html) or html[i] != "[":
        return None
    depth = 0
    end = i
    in_str = esc = False
    while end < len(html):
        ch = html[end]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
        end += 1
    try:
        return json.loads(html[i:end])
    except Exception:
        return None


def lowest_price(rooms, min_persons=2):
    best = None
    for rt in rooms or []:
        for b in rt.get("b_blocks") or []:
            if (b.get("b_max_persons") or 0) < min_persons:
                continue
            try:
                raw = float(b.get("b_raw_price") or 0)
            except Exception:
                continue
            if raw > 0 and (best is None or raw < best):
                best = raw
    return best


def scrape_booking(url):
    try:
        r = requests.post(
            f"{API}/scrape",
            json={
                "url": url,
                "waitFor": 10000,
                "timeout": 90000,
                "ignoreHttpsErrors": True,
            },
            timeout=180,
        )
        resp = r.json()
    except Exception as e:
        return {"error": str(e)}
    if not resp.get("success"):
        return {"error": resp.get("error", "unknown")}
    html = resp["data"]["rawHtml"]
    rooms = extract_room_blob(html)
    price = lowest_price(rooms) if rooms else None
    return {
        "html_size": len(html),
        "has_blob": rooms is not None,
        "price": price,
        "n_blocks": sum(len(rt.get("b_blocks") or []) for rt in (rooms or [])),
    }


# Load latest snapshot for this hotel
latest_date = sorted(d for d in SNAPSHOT_DIR.iterdir() if d.is_dir())[-1].name
snapshot = json.loads((SNAPSHOT_DIR / latest_date / f"{HOTEL_ID}.json").read_text())
month = CHECKIN[:7]
month_data = next((m for m in snapshot["months"] if m["month"] == month), None)
if not month_data:
    print(f"[!] no {month} data in snapshot for hotel {HOTEL_ID}")
    sys.exit(1)

# Find the date row
date_row = next((r for r in month_data["rates"] if r["date"] == CHECKIN), None)
if not date_row:
    print(f"[!] no rate row for {CHECKIN}")
    sys.exit(1)

# Build targets: one per competitor with a booking URL
targets = []
for hi_id, cell in date_row["hotels"].items():
    comp = snapshot["competitors"].get(hi_id, {})
    base_url = comp.get("booking_base_url")
    if not base_url:
        continue
    targets.append(
        {
            "hotelinfo_id": hi_id,
            "name": comp.get("name", "?"),
            "is_own": comp.get("is_own", False),
            "lh_value": cell.get("value"),
            "lh_shop_value": cell.get("shop_value"),
            "lh_currency": cell.get("currency"),
            "lh_room": cell.get("room_name"),
            "lh_message": cell.get("message"),
            "booking_url": lock_dates(base_url, CHECKIN, CHECKOUT),
        }
    )

print(f"[*] Hotel {HOTEL_ID} ({snapshot['hotel_name'][:50]})")
print(f"[*] Check-in {CHECKIN} → Check-out {CHECKOUT} ({LOS} nights)")
print(f"[*] {len(targets)} competitors to scrape, concurrency={CONCURRENCY}")
print()

# Scrape all booking URLs
results = []
with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
    futures = {ex.submit(scrape_booking, t["booking_url"]): t for t in targets}
    for fut in as_completed(futures):
        t = futures[fut]
        bc = fut.result()
        t["bc"] = bc
        results.append(t)
        tag = f"${bc['price']:.0f}" if bc.get("price") else (bc.get("error", "no blob")[:30])
        print(f"  {t['name'][:45]:<45}  LH=${t['lh_value'] or 0:>6.2f}  BC={tag}", flush=True)
        time.sleep(random.uniform(0.3, 1.0))

# Summary comparison
print()
print(f"{'Property':<45} {'LH $/nt':>8} {'LH 7-nt':>8} {'BC 7-nt':>8} {'Δ':>7} {'Match':>6}")
print("-" * 95)
ok = close = far = missing = 0
for r in sorted(results, key=lambda x: x["name"]):
    lh_night = r["lh_value"] or 0
    lh_shop = r["lh_shop_value"] or 0
    bc_price = r["bc"].get("price") or 0
    name = r["name"][:44]
    own = "★" if r["is_own"] else " "

    if bc_price == 0:
        status = "no BC"
        missing += 1
        delta = ""
    elif lh_shop == 0:
        status = "no LH"
        missing += 1
        delta = ""
    else:
        d = bc_price - lh_shop
        pct = abs(d / lh_shop * 100) if lh_shop else 0
        delta = f"{d:+.0f}"
        if pct < 5:
            status = "OK"
            ok += 1
        elif pct < 15:
            status = "~close"
            close += 1
        else:
            status = "!!FAR"
            far += 1

    print(
        f"{own}{name:<44} ${lh_night:>7.2f} ${lh_shop:>7.0f} ${bc_price:>7.0f} {delta:>7} {status:>6}"
    )

print("-" * 95)
print(
    f"OK (<5%): {ok}  |  Close (5-15%): {close}  |  Far (>15%): {far}  |  Missing: {missing}  |  Total: {len(results)}"
)

# Save
out = Path("output") / f"compare_{HOTEL_ID}_{CHECKIN}.json"
out.write_text(
    json.dumps(
        {
            "hotel_id": HOTEL_ID,
            "checkin": CHECKIN,
            "checkout": CHECKOUT,
            "scraped_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "results": results,
        },
        indent=2,
        default=str,
    )
)
print(f"\n[*] saved to {out}")
