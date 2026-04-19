"""Scrape every May Booking.com URL from all_data.json via Firecrawl, locked to
the week of May 13-20, 2026. Compares Booking.com's 'Price for 1 week' against
Lighthouse's shop_value for the same date.
"""

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

OUT = Path(os.environ.get("OUT_DIR", "output"))
ALL_DATA = OUT / "all_data.json"
FIRECRAWL_KEY = os.environ["FIRECRAWL_KEY"]
FIRECRAWL_URL = "https://api.firecrawl.dev/v1/scrape"

CHECKIN = "2026-05-13"
CHECKOUT = "2026-05-20"

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "lowest_price_for_one_week": {
            "type": "number",
            "description": "Lowest dollar value (numeric only, no currency symbol) shown in the 'Price for 1 week' column of the availability table.",
        },
        "currency": {"type": "string"},
        "room_type": {
            "type": "string",
            "description": "Room type label of the cheapest 7-night row (e.g. 'Double Room - Disability Access - Non-Smoking').",
        },
        "number_of_guests": {"type": "integer"},
        "sold_out": {
            "type": "boolean",
            "description": "True if the page shows 'Sold out' / no availability instead of pricing.",
        },
    },
}

EXTRACT_PROMPT = (
    "Find the room availability table on this Booking.com hotel page. "
    "Inside it, find the column titled 'Price for 1 week' (this is the 7-night "
    "total). Return the LOWEST numeric value visible in that column for a "
    "2-guest occupancy. Strip currency symbols. If the page shows 'Sold out' / "
    "no availability, set sold_out=true and lowest_price_for_one_week=0."
)


def lock_dates(url: str, checkin: str, checkout: str) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["checkin"] = checkin
    q["checkout"] = checkout
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def collect_urls() -> list[dict]:
    """One row per (subscription, hotelinfo) with a non-zero May rate, deduped by Booking.com slug."""
    data = json.loads(ALL_DATA.read_text())
    out: list[dict] = []
    seen_slugs: set[str] = set()

    for sub in data["subscriptions"]:
        may = next((m for m in sub["months"] if m["month"] == "2026-05"), None)
        if not may:
            continue

        # Collect this subscription's name lookup + base URL lookup.
        names: dict[str, str] = {}
        bases: dict[str, str] = {}
        if sub.get("own_hotelinfo"):
            names[sub["own_hotelinfo"]["id"]] = sub["own_hotelinfo"]["name"]
            if sub["own_hotelinfo"].get("booking_base_url"):
                bases[sub["own_hotelinfo"]["id"]] = sub["own_hotelinfo"]["booking_base_url"]
        for c in sub["competitors"]:
            names[c["hotelinfo_id"]] = c["name"]
            if c.get("booking_base_url"):
                bases[c["hotelinfo_id"]] = c["booking_base_url"]

        # Pick the rate row that matches our locked check-in date if present;
        # otherwise the first row with a non-zero rate (so we still capture the
        # property even when 5/13 is missing).
        rate_row = next((r for r in may["rates_by_date"] if r["date"] == CHECKIN), None)

        for hi_id, base_url in bases.items():
            slug = urlsplit(base_url).path
            if slug in seen_slugs:
                continue

            # Look up Lighthouse's value for this hotelinfo on 5/13 (if present).
            lh_rate = None
            if rate_row:
                lh_rate = rate_row["competitors"].get(hi_id)
            # Fallback: any non-zero rate in May.
            if not lh_rate or (lh_rate.get("value") or 0) == 0:
                for r in may["rates_by_date"]:
                    rec = r["competitors"].get(hi_id)
                    if rec and (rec.get("value") or 0) > 0:
                        lh_rate = rec
                        break

            if not lh_rate:
                continue  # no May data at all for this hotel

            seen_slugs.add(slug)
            out.append(
                {
                    "subscription_hotel_id": sub["hotel_id"],
                    "subscription_hotel_name": sub["hotel_name"],
                    "hotelinfo_id": hi_id,
                    "property_name": names.get(hi_id, "?"),
                    "checkin": CHECKIN,
                    "checkout": CHECKOUT,
                    "booking_url": lock_dates(base_url, CHECKIN, CHECKOUT),
                    "lighthouse_value_per_night": lh_rate.get("value"),
                    "lighthouse_shop_value": lh_rate.get("shop_value"),
                    "lighthouse_currency": lh_rate.get("currency"),
                    "lighthouse_room_name": lh_rate.get("room_name"),
                    "lighthouse_message": lh_rate.get("message"),
                }
            )
    return out


def firecrawl_scrape(url: str) -> dict:
    payload = {
        "url": url,
        "formats": ["json"],
        "jsonOptions": {"prompt": EXTRACT_PROMPT, "schema": EXTRACT_SCHEMA},
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
    targets = collect_urls()
    if not targets:
        print("[!] no May targets in all_data.json", file=sys.stderr)
        return 2
    print(f"[*] {len(targets)} unique May URLs to scrape (locked to {CHECKIN} → {CHECKOUT})")

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
        if extracted:
            print(
                f"    HTTP {resp['http_status']} → ${extracted.get('lowest_price_for_one_week')} {extracted.get('currency', '')}  room='{(extracted.get('room_type') or '')[:55]}'  sold_out={extracted.get('sold_out')}"
            )
        else:
            err = body.get("error") if isinstance(body, dict) else str(body)[:200]
            print(f"    HTTP {resp['http_status']} → no extraction: {err}")
        results.append(
            {
                **t,
                "firecrawl_http_status": resp["http_status"],
                "firecrawl_success": bool(ok),
                "firecrawl_extracted": extracted,
                "firecrawl_error": (
                    body.get("error") if isinstance(body, dict) and not ok else None
                ),
                "extracted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
        )
        # Periodically save progress so a long run isn't lost.
        if i % 10 == 0:
            (OUT / "firecrawl_may.json").write_text(
                json.dumps(
                    {
                        "scraped_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                        "checkin": CHECKIN,
                        "checkout": CHECKOUT,
                        "results": results,
                    },
                    indent=2,
                    default=str,
                )
            )
        time.sleep(0.5)

    out_path = OUT / "firecrawl_may.json"
    out_path.write_text(
        json.dumps(
            {
                "scraped_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "checkin": CHECKIN,
                "checkout": CHECKOUT,
                "results": results,
            },
            indent=2,
            default=str,
        )
    )
    n_ok = sum(1 for r in results if r.get("firecrawl_success"))
    n_sold = sum(1 for r in results if (r.get("firecrawl_extracted") or {}).get("sold_out"))
    print(f"\n[*] wrote {out_path} — {n_ok}/{len(results)} extracted ({n_sold} sold out)")
    return 0 if n_ok else 1


if __name__ == "__main__":
    sys.exit(main())
