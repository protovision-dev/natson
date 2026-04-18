"""Daily Lighthouse scrape orchestrator.

Workflow (sequential per hotel, never concurrent):
  1. Login session loaded from output/session.json
  2. For each hotel in hotels.json:
     a. Trigger refresh for each rolling month (POST /liveshop)
     b. Poll /liveupdates until each refresh completes
     c. Fetch rate grids for all months (GET /rates/)
     d. Fetch metadata (cached: subscription info, hotelinfos, booking URLs)
     e. Build snapshot and write to output/snapshots/{date}/{hotel_id}.json
  3. Write daily summary

Usage:
  .venv/bin/python scrape.py                    # all hotels, 3 rolling months
  .venv/bin/python scrape.py --hotel 345062     # one hotel only (Phase 1 test)
  .venv/bin/python scrape.py --no-refresh       # skip refresh, just scrape existing data
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

from config import (
    API_BASE, RATES_API, HOTELS_API, HOTELINFOS_API, REDIRECT_API,
    OUT_DIR, SESSION_FILE, CACHE_DIR,
    POLITE_SLEEP, build_targets, load_hotels_config, grid_range, swap_dates,
    build_rates_api_url, month_range,
)

DEMAND_API = f"{API_BASE}/apigateway/v1/app/demand/ari/demands/"
from refresh import refresh_and_wait
from snapshot import save_hotel_snapshot, save_daily_summary

# ---------- cache ----------

_refresh = os.environ.get("REFRESH_META", "").lower()
REFRESH_ALL = _refresh in ("1", "true", "yes", "all")
REFRESH_HOTELS = REFRESH_ALL or "hotels" in _refresh
REFRESH_HOTELINFOS = REFRESH_ALL or "hotelinfos" in _refresh
REFRESH_URLS = REFRESH_ALL or "urls" in _refresh

HOTELS_CACHE = CACHE_DIR / "hotels.json"
HOTELINFOS_CACHE = CACHE_DIR / "hotelinfos.json"

def booking_urls_cache_path(ota: str) -> Path:
    """/redirect resolves differently per OTA, so cache per OTA."""
    suffix = "" if ota == "bookingdotcom" else f"_{ota}"
    return CACHE_DIR / f"booking_base_urls{suffix}.json"


def load_cache(path: Path, force_refresh: bool) -> dict:
    if force_refresh or not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def save_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str, sort_keys=True))


# ---------- API helpers ----------

def make_session() -> requests.Session:
    s_data = json.loads(SESSION_FILE.read_text())
    s = requests.Session()
    for c in s_data["cookies"]:
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    s.headers.update({
        "User-Agent": s_data["user_agent"],
        "Accept": "application/json, text/plain, */*",
        "Origin": API_BASE,
    })
    return s


def fetch_rates(sess, hotel_id, month, compset_id=1, los=7, persons=2, ota="bookingdotcom"):
    url = build_rates_api_url(hotel_id, month, compset_id, los, persons, ota)
    r = sess.get(url, headers={"Referer": f"{API_BASE}/hotel/{hotel_id}/rates"}, timeout=60)
    r.raise_for_status()
    return url, r.json()


def fetch_subscription_meta(sess, hotel_id):
    r = sess.get(HOTELS_API, params={"id": hotel_id}, timeout=30)
    r.raise_for_status()
    hotels = r.json().get("hotels", [])
    return hotels[0] if hotels else None


def fetch_hotelinfo(sess, hotelinfo_id):
    r = sess.get(f"{HOTELINFOS_API}{hotelinfo_id}/", timeout=30)
    if r.status_code != 200:
        return None
    items = r.json().get("hotelinfos", [])
    return items[0] if items else None


def resolve_booking_base_url(sess, hotel_id, hotelinfo_id, seed_date, los, persons,
                              ota="bookingdotcom"):
    params = {
        "ota": ota, "hotelId": hotelinfo_id, "direct": "false",
        "fromDate": seed_date, "los": los, "persons": persons,
        "city": "false", "subscription_id": hotel_id, "pos": "", "source": "app_rates",
    }
    r = sess.get(REDIRECT_API, params=params, allow_redirects=True, timeout=30)
    return r.url if r.url and r.url.startswith("http") and "mylighthouse.com" not in r.url else None


def fetch_demand(sess, hotel_id, month):
    """Fetch market demand scores for a hotel+month. Returns {date: value} dict."""
    start, end = month_range(month)
    r = sess.get(DEMAND_API, params={
        "from_date_range_start": start,
        "from_date_range_end": end,
        "subscription_id": hotel_id,
    }, timeout=30)
    r.raise_for_status()
    out = {}
    for d in r.json().get("demands", []):
        v = d.get("value")
        if v and v > 0:
            out[d["day"]] = round(v * 100, 1)  # 0.974 → 97.4
    return out


def pick_primary_rate(records):
    for r in records:
        if (r.get("value") or 0) > 0:
            return r
    return records[0] if records else None


def slim_rate(r):
    keys = [
        "value", "currency", "shop_value", "shop_currency",
        "room_name", "room_type", "cema_category",
        "best_flex", "cancellable", "cancellation",
        "city_tax", "vat", "other_taxes",
        "city_tax_incl", "vat_incl", "other_taxes_incl",
        "extract_datetime", "is_out_of_sync", "max_persons",
        "message", "platform", "membershiptype", "mealtype_included",
        "is_baserate", "difference_with_baserate",
    ]
    return {k: r.get(k) for k in keys if k in r}


# ---------- main ----------

def scrape_one_hotel(
    sess: requests.Session,
    hotel_id: str,
    hotel_name: str,
    months: list[str],
    compset_id: int,
    los: int,
    persons: int,
    ota: str,
    do_refresh: bool,
    hotels_cache: dict,
    hotelinfos_cache: dict,
    booking_cache: dict,
) -> dict:
    """Refresh + scrape one hotel across all months. Returns snapshot dict."""

    scrape_date = date.today().isoformat()
    hotel_result = {
        "scrape_date": scrape_date,
        "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "hotel_id": hotel_id,
        "hotel_name": hotel_name,
        "compset_id": compset_id,
        "los": los,
        "persons": persons,
    }

    # --- Subscription metadata (cached) ---
    if hotel_id in hotels_cache:
        sub_meta = hotels_cache[hotel_id]
    else:
        sub_meta = fetch_subscription_meta(sess, hotel_id) or {}
        hotels_cache[hotel_id] = sub_meta
        time.sleep(POLITE_SLEEP)

    own_hi = str(sub_meta.get("hotelinfo")) if sub_meta.get("hotelinfo") else None
    hotel_result["own_hotelinfo_id"] = own_hi

    # --- Refresh + scrape each month (interleaved) ---
    # Each month is refreshed and then immediately scraped before moving to
    # the next, so the data captured is as fresh as possible.
    refresh_results = {}
    all_hotelinfo_ids: set[str] = set()
    months_data = []
    for mi, month in enumerate(months):
        if do_refresh:
            result = refresh_and_wait(sess, hotel_id, month, compset_id, los, persons, ota)
            refresh_results[month] = result
        try:
            api_url, body = fetch_rates(sess, hotel_id, month, compset_id, los, persons, ota)
        except Exception as e:
            print(f"  [!] rates failed for {month}: {e}", flush=True)
            continue
        for period in body.get("periods", []):
            for hid in (period.get("rates") or {}).keys():
                all_hotelinfo_ids.add(str(hid))
        # Fetch market demand for this month.
        try:
            demand = fetch_demand(sess, hotel_id, month)
        except Exception:
            demand = {}
        months_data.append({"month": month, "api_url": api_url, "body": body, "demand": demand})
        # Jitter between months (skip after the last month).
        if mi < len(months) - 1:
            jitter = random.uniform(2, 6)
            print(f"    (waiting {jitter:.1f}s before next month)", flush=True)
            time.sleep(jitter)
    hotel_result["refreshes"] = refresh_results

    if own_hi:
        all_hotelinfo_ids.add(own_hi)

    # --- Hotelinfo metadata (cached) ---
    for hi in sorted(all_hotelinfo_ids):
        if hi not in hotelinfos_cache:
            hotelinfos_cache[hi] = fetch_hotelinfo(sess, hi) or {}
            time.sleep(POLITE_SLEEP)

    # --- Booking.com URLs (cached) ---
    for hi in sorted(all_hotelinfo_ids):
        cache_key = f"{hotel_id}:{hi}"
        if cache_key not in booking_cache:
            seed_date = None
            for md in months_data:
                for p in md["body"].get("periods", []):
                    if p.get("from_date"):
                        seed_date = p["from_date"]
                        break
                if seed_date:
                    break
            if seed_date:
                try:
                    url = resolve_booking_base_url(sess, hotel_id, hi, seed_date, los, persons, ota)
                except Exception:
                    url = None
                booking_cache[cache_key] = url
                time.sleep(POLITE_SLEEP)

    # --- Build competitors block ---
    competitors = {}
    for hi in sorted(all_hotelinfo_ids):
        meta = hotelinfos_cache.get(hi, {})
        cache_key = f"{hotel_id}:{hi}"
        competitors[hi] = {
            "name": meta.get("name"),
            "stars": meta.get("stars"),
            "country": meta.get("country"),
            "latitude": meta.get("latitude"),
            "longitude": meta.get("longitude"),
            "hotel_group": meta.get("hotel_group"),
            "is_own": hi == own_hi,
            "booking_base_url": booking_cache.get(cache_key),
        }
    hotel_result["competitors"] = competitors

    # --- Build rate grid per month ---
    hotel_result["months"] = []
    total_rates = 0
    for md in months_data:
        start, end = month_range(md["month"])
        demand_by_date = md.get("demand", {})
        rates_list = []
        for period in md["body"].get("periods", []):
            d = period.get("from_date")
            checkout = (date.fromisoformat(d) + timedelta(days=los)).isoformat() if d else None
            hotels_cells = {}
            for hi_id, recs in (period.get("rates") or {}).items():
                primary = pick_primary_rate(recs)
                if primary is None:
                    continue
                base_url = booking_cache.get(f"{hotel_id}:{hi_id}")
                cell = slim_rate(primary)
                cell["booking_url"] = swap_dates(base_url, d, los) if base_url and d else None
                hotels_cells[str(hi_id)] = cell
                total_rates += 1
            rates_list.append({
                "date": d,
                "checkout_date": checkout,
                "leadtime_days": period.get("leadtime"),
                "market_demand_pct": demand_by_date.get(d),
                "hotels": hotels_cells,
            })
        hotel_result["months"].append({
            "month": md["month"],
            "date_range": [start, end],
            "rates": rates_list,
        })

    hotel_result["total_rate_cells"] = total_rates
    return hotel_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Lighthouse scrape")
    parser.add_argument("--hotel", type=str, help="Scrape only this hotel ID (Phase 1 test)")
    parser.add_argument("--no-refresh", action="store_true", help="Skip refresh, just scrape existing data")
    parser.add_argument("--ota", type=str, default=None,
                        help="Override OTA for all hotels (e.g. branddotcom). Default: per-hotel from hotels.json.")
    args = parser.parse_args()

    if not SESSION_FILE.exists():
        print(f"[!] {SESSION_FILE} missing — run login.py first", file=sys.stderr)
        return 2

    config = load_hotels_config()
    hotel_ids = [args.hotel] if args.hotel else None
    targets = build_targets(config, hotel_ids=hotel_ids)
    if not targets:
        print("[!] no targets", file=sys.stderr)
        return 2

    # Group targets by hotel.
    from collections import defaultdict
    by_hotel: dict[str, dict] = {}
    for t in targets:
        hid = t["hotel_id"]
        if hid not in by_hotel:
            by_hotel[hid] = {
                "hotel_name": t["hotel_name"],
                "compset_id": t["compset_id"],
                "los": t["los"],
                "persons": t["persons"],
                "ota": args.ota or t["ota"],
                "months": [],
            }
        by_hotel[hid]["months"].append(t["month"])

    sess = make_session()
    today = date.today().isoformat()
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    do_refresh = not args.no_refresh

    # Effective OTA for output naming: if all hotels share one ota, use that; otherwise "mixed".
    otas_in_run = {info["ota"] for info in by_hotel.values()}
    run_ota = otas_in_run.pop() if len(otas_in_run) == 1 else "mixed"
    ota_suffix = "" if run_ota == "bookingdotcom" else f"_{run_ota}"

    print(f"[*] {len(by_hotel)} hotel(s), {len(targets)} (hotel, month) targets")
    print(f"[*] scrape_date={today}  refresh={'ON' if do_refresh else 'OFF'}  ota={run_ota}")

    # Load caches. booking_base_urls cache is per-OTA (redirect returns OTA-specific URLs).
    hotels_cache = load_cache(HOTELS_CACHE, REFRESH_HOTELS)
    hotelinfos_cache = load_cache(HOTELINFOS_CACHE, REFRESH_HOTELINFOS)
    booking_urls_cache_file = booking_urls_cache_path(run_ota)
    booking_cache = load_cache(booking_urls_cache_file, REFRESH_URLS)

    summary_results = []
    for i, (hotel_id, info) in enumerate(by_hotel.items(), 1):
        print(f"\n{'='*60}", flush=True)
        print(f"[{i}/{len(by_hotel)}] {info['hotel_name']}", flush=True)
        print(f"    hotel_id={hotel_id}  months={info['months']}", flush=True)

        t0 = time.time()
        try:
            snapshot = scrape_one_hotel(
                sess, hotel_id, info["hotel_name"], info["months"],
                info["compset_id"], info["los"], info["persons"], info["ota"],
                do_refresh, hotels_cache, hotelinfos_cache, booking_cache,
            )
            path = save_hotel_snapshot(hotel_id, snapshot, today, ota_suffix=ota_suffix)
            duration = time.time() - t0
            print(f"  [ok] {snapshot['total_rate_cells']} rate cells → {path.name} ({duration:.0f}s)", flush=True)
            summary_results.append({
                "hotel_id": hotel_id,
                "hotel_name": info["hotel_name"],
                "status": "ok",
                "duration_s": round(duration, 1),
                "rates_count": snapshot["total_rate_cells"],
                "months": info["months"],
            })
        except Exception as e:
            duration = time.time() - t0
            print(f"  [FAIL] {type(e).__name__}: {e}", flush=True)
            summary_results.append({
                "hotel_id": hotel_id,
                "hotel_name": info["hotel_name"],
                "status": "failed",
                "duration_s": round(duration, 1),
                "error": str(e),
            })

        # Jitter between hotels (skip after the last one).
        if i < len(by_hotel):
            jitter = random.uniform(5, 15)
            print(f"\n  (waiting {jitter:.1f}s before next hotel)", flush=True)
            time.sleep(jitter)

    # Save caches.
    save_cache(HOTELS_CACHE, hotels_cache)
    save_cache(HOTELINFOS_CACHE, hotelinfos_cache)
    save_cache(booking_urls_cache_file, booking_cache)

    # Save daily summary.
    summary_path = save_daily_summary(summary_results, started_at, today, ota_suffix=ota_suffix)
    ok = sum(1 for r in summary_results if r["status"] == "ok")
    print(f"\n[*] {ok}/{len(summary_results)} hotels scraped → {summary_path}")
    return 0 if ok == len(summary_results) else 1


if __name__ == "__main__":
    sys.exit(main())
