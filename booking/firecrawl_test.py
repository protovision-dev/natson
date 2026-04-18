"""Test pulling Booking.com 'Price for 1 week' via Firecrawl for 10 May URLs.

Picks one competitor per subscription hotel (where May rate is non-zero), hits
Firecrawl with a JSON-extraction schema asking for the lowest week price, and
saves a sidecar JSON comparing Lighthouse's shop_value to what Booking.com
returns.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(os.environ.get("OUT_DIR", "output"))
ALL_DATA = OUT / "all_data.json"
FIRECRAWL_KEY = os.environ["FIRECRAWL_KEY"]
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"
LIMIT = int(os.environ.get("LIMIT", "10"))

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "lowest_price_for_one_week": {
            "type": "number",
            "description": "Lowest dollar value (numeric only) shown in the 'Price for 1 week' column of the availability table. Strip any currency symbol.",
        },
        "currency": {"type": "string"},
        "room_type": {
            "type": "string",
            "description": "The room type label of the cheapest 7-night row (e.g. 'Double Room - Disability Access - Non-Smoking').",
        },
        "number_of_guests": {"type": "integer"},
        "sold_out": {
            "type": "boolean",
            "description": "True if the page shows 'Sold out' / 'No availability' instead of pricing.",
        },
    },
}

EXTRACT_PROMPT = (
    "Find the room availability table on this Booking.com hotel page. "
    "Inside it, find the column titled 'Price for 1 week' (this is the 7-night "
    "total). Return the LOWEST numeric value visible in that column for a 2-guest "
    "occupancy. Strip currency symbols. If the page shows 'Sold out' / no "
    "availability, set sold_out=true and lowest_price_for_one_week=0."
)


def pick_targets() -> list[dict]:
    """One distinct competitor per subscription hotel from May data."""
    data = json.loads(ALL_DATA.read_text())
    rows: list[dict] = []
    for sub in data["subscriptions"]:
        may = next((m for m in sub["months"] if m["month"] == "2026-05"), None)
        if not may:
            continue

        # Build hotelinfo_id → name lookup (own + competitors)
        names = {}
        if sub.get("own_hotelinfo"):
            names[sub["own_hotelinfo"]["id"]] = sub["own_hotelinfo"]["name"]
        for c in sub["competitors"]:
            names[c["hotelinfo_id"]] = c["name"]

        # Walk dates, find first competitor with a real rate + valid booking_url.
        chosen = None
        for date_row in may["rates_by_date"]:
            for hi_id, rate in date_row["competitors"].items():
                if (rate.get("value") or 0) > 0 and rate.get("booking_url"):
                    chosen = {
                        "subscription_hotel_id": sub["hotel_id"],
                        "subscription_hotel_name": sub["hotel_name"],
                        "competitor_hotelinfo_id": hi_id,
                        "property_name": names.get(hi_id, "?"),
                        "checkin": date_row["date"],
                        "checkout": date_row["checkout_date"],
                        "lighthouse_value_per_night": rate.get("value"),
                        "lighthouse_shop_value": rate.get("shop_value"),
                        "lighthouse_currency": rate.get("currency"),
                        "lighthouse_room_name": rate.get("room_name"),
                        "booking_url": rate["booking_url"],
                    }
                    break
            if chosen:
                break
        if chosen:
            rows.append(chosen)
    return rows[:LIMIT]


def firecrawl_scrape(url: str) -> dict:
    payload = {
        "url": url,
        "formats": ["json"],
        "jsonOptions": {
            "prompt": EXTRACT_PROMPT,
            "schema": EXTRACT_SCHEMA,
        },
        "onlyMainContent": True,
        "waitFor": 2500,
    }
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_KEY}",
        "Content-Type": "application/json",
    }
    r = requests.post(FIRECRAWL_URL, headers=headers, json=payload, timeout=180)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:1000]}
    return {"http_status": r.status_code, "body": body}


def main() -> int:
    targets = pick_targets()
    if not targets:
        print("[!] no targets — does all_data.json have May rates?", file=sys.stderr)
        return 2
    print(f"[*] testing {len(targets)} URLs via Firecrawl")

    results = []
    for i, t in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {t['property_name']}")
        print(f"    {t['booking_url'][:160]}")
        try:
            resp = firecrawl_scrape(t["booking_url"])
        except Exception as e:
            print(f"    [err] {e}")
            results.append({**t, "firecrawl_error": str(e)})
            continue
        body = resp["body"]
        ok = isinstance(body, dict) and body.get("success") and body.get("data", {}).get("json")
        extracted = body["data"]["json"] if ok else None
        print(f"    HTTP {resp['http_status']} success={ok}")
        if extracted:
            print(f"    → ${extracted.get('lowest_price_for_one_week')} {extracted.get('currency','')} room='{(extracted.get('room_type') or '')[:60]}'")
        else:
            err = body.get("error") if isinstance(body, dict) else str(body)[:200]
            print(f"    → no extraction: {err}")
        results.append({
            **t,
            "firecrawl_http_status": resp["http_status"],
            "firecrawl_success": bool(ok),
            "firecrawl_extracted": extracted,
            "firecrawl_error": (body.get("error") if isinstance(body, dict) and not ok else None),
            "extracted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        time.sleep(1.0)

    out_path = OUT / "firecrawl_test.json"
    out_path.write_text(json.dumps({
        "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "limit": LIMIT,
        "results": results,
    }, indent=2, default=str))
    n_ok = sum(1 for r in results if r.get("firecrawl_success"))
    print(f"\n[*] wrote {out_path} ({n_ok}/{len(results)} extracted)")
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
