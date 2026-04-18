"""Compare Lighthouse vs Booking.com for one property, entire month.

Fires one Firecrawl request per (competitor, date) — 10 hotels × 31 days = 310 URLs.
High concurrency via ThreadPoolExecutor.

Usage: .venv/bin/python compare_month.py [hotel_id] [month]
Default: 345062 2026-05
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests

FIRECRAWL_KEY = os.environ.get("FIRECRAWL_KEY")
if not FIRECRAWL_KEY:
    sys.exit("[!] FIRECRAWL_KEY env var required")
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
CONCURRENCY = int(os.environ.get("CONCURRENCY", "25"))
HOTEL_ID = sys.argv[1] if len(sys.argv) > 1 else "345062"
MONTH = sys.argv[2] if len(sys.argv) > 2 else "2026-05"
LOS = 7

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "lowest_price_for_one_week": {"type": "number"},
        "currency": {"type": "string"},
        "room_type": {"type": "string"},
        "sold_out": {"type": "boolean"},
    },
}
EXTRACT_PROMPT = (
    "Find the room availability table. Return the LOWEST numeric value in the "
    '"Price for 1 week" column for 2-guest occupancy. Strip currency symbols. '
    "If sold out, set sold_out=true and lowest_price_for_one_week=0."
)


def lock_dates(url, checkin, los):
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["checkin"] = checkin
    q["checkout"] = (date.fromisoformat(checkin) + timedelta(days=los)).isoformat()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def firecrawl_one(url):
    try:
        r = requests.post(FIRECRAWL_URL,
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["json"],
                  "jsonOptions": {"prompt": EXTRACT_PROMPT, "schema": EXTRACT_SCHEMA},
                  "onlyMainContent": True, "waitFor": 2500},
            timeout=180)
        body = r.json()
        if body.get("success") and body.get("data", {}).get("json"):
            return body["data"]["json"]
        return {"error": body.get("error", "no json")}
    except Exception as e:
        return {"error": str(e)[:200]}


# Load snapshot
latest = sorted(d for d in Path("output/snapshots").iterdir() if d.is_dir())[-1].name
snapshot = json.loads(Path(f"output/snapshots/{latest}/{HOTEL_ID}.json").read_text())
month_data = next((m for m in snapshot["months"] if m["month"] == MONTH), None)
if not month_data:
    print(f"[!] no {MONTH} data in snapshot")
    sys.exit(1)

# Build all (date, competitor) targets
targets = []
for row in month_data["rates"]:
    d = row["date"]
    for hi_id, cell in row["hotels"].items():
        comp = snapshot["competitors"].get(hi_id, {})
        base_url = comp.get("booking_base_url")
        if not base_url:
            continue
        targets.append({
            "date": d,
            "hotelinfo_id": hi_id,
            "name": comp.get("name"),
            "is_own": comp.get("is_own", False),
            "lh_value": cell.get("value"),
            "lh_shop_value": cell.get("shop_value"),
            "lh_room": cell.get("room_name"),
            "lh_message": cell.get("message"),
            "booking_url": lock_dates(base_url, d, LOS),
        })

print(f"[*] Hotel {HOTEL_ID} ({snapshot['hotel_name'][:50]})")
print(f"[*] Month: {MONTH}  |  {len(month_data['rates'])} dates × {len(snapshot['competitors'])} competitors = {len(targets)} URLs")
print(f"[*] Concurrency: {CONCURRENCY}")
print()

# Fire all requests
t0 = time.time()
done = 0
results = []

def worker(t):
    ext = firecrawl_one(t["booking_url"])
    return {**t, "bc": ext}

with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
    futures = {ex.submit(worker, t): t for t in targets}
    for fut in as_completed(futures):
        r = fut.result()
        results.append(r)
        done += 1
        if done % 25 == 0 or done == len(targets):
            elapsed = time.time() - t0
            rate = done / elapsed
            eta = (len(targets) - done) / rate if rate > 0 else 0
            print(f"  [{done}/{len(targets)}]  {elapsed:.0f}s elapsed  {rate:.1f}/s  ETA {eta:.0f}s", flush=True)

elapsed = time.time() - t0
print(f"\n[*] {len(results)} results in {elapsed:.0f}s ({len(results)/elapsed:.1f}/s)")

# Save raw results
out_path = Path(f"output/compare_month_{HOTEL_ID}_{MONTH}.json")
out_path.write_text(json.dumps({
    "hotel_id": HOTEL_ID, "month": MONTH, "method": "firecrawl",
    "concurrency": CONCURRENCY, "elapsed_s": round(elapsed, 1),
    "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "results": results,
}, indent=2, default=str))
print(f"[*] saved to {out_path}")

# Compare
print(f"\n{'date':<12} {'Property':<35} {'LH 7nt':>7} {'BC 7nt':>7} {'Δ':>6} {'Match':>6}")
print("-" * 85)

ok = close = far = miss = sold = 0
by_date = {}
for r in sorted(results, key=lambda x: (x["date"], x["name"])):
    lh = r["lh_shop_value"] or 0
    bc_ext = r["bc"]
    bc = bc_ext.get("lowest_price_for_one_week") or 0 if isinstance(bc_ext, dict) and "error" not in bc_ext else 0
    bc_sold = bc_ext.get("sold_out", False) if isinstance(bc_ext, dict) else False
    err = bc_ext.get("error") if isinstance(bc_ext, dict) else None

    if err:
        status = "ERR"
        miss += 1
        delta = ""
    elif bc_sold or bc == 0:
        status = "SOLD"
        sold += 1
        delta = ""
    elif lh == 0:
        status = "noLH"
        miss += 1
        delta = ""
    else:
        d = bc - lh
        pct = abs(d / lh * 100)
        delta = f"{d:+.0f}"
        if pct < 5:
            status = "OK"
            ok += 1
        elif pct < 15:
            status = "~"
            close += 1
        else:
            status = "FAR"
            far += 1

    by_date.setdefault(r["date"], []).append(status)

# Print summary by date
print("\nPer-date summary:")
for d in sorted(by_date):
    statuses = by_date[d]
    n_ok = sum(1 for s in statuses if s == "OK")
    n_close = sum(1 for s in statuses if s == "~")
    n_far = sum(1 for s in statuses if s == "FAR")
    n_sold = sum(1 for s in statuses if s == "SOLD")
    n_err = sum(1 for s in statuses if s in ("ERR", "noLH"))
    print(f"  {d}  OK={n_ok}  close={n_close}  far={n_far}  sold={n_sold}  err={n_err}  / {len(statuses)}")

total = len(results)
print(f"\nTotal: {total}  OK: {ok} ({ok/total*100:.0f}%)  Close: {close}  Far: {far}  Sold: {sold}  Missing: {miss}")
