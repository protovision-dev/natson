"""Per-hotel Lighthouse scrape — library functions driven by a Job spec.

This module is no longer an entrypoint.  Use `run_job.py` for the CLI.

Public surface:
    scrape_hotel(sess, job, hotel_id, caches) -> snapshot dict

Responsibilities:
    - If job.do_refresh: trigger /liveshop for each ≤31-day refresh window
      and poll to completion before fetching rates.
    - If job.refresh_only: trigger + poll, then return (no rates fetch).
    - Otherwise: fetch /rates once for the whole span (API supports
      arbitrary date ranges), then filter response periods down to
      job.checkin_dates, attach market demand + competitor metadata +
      per-cell Booking.com URLs, and return the snapshot.

Caches (subscription meta, hotelinfo meta, per-(hotel,hotelinfo) OTA
redirect URLs) live in dicts owned by the caller (run_job.py), which
loads/saves them once per invocation from output/cache/.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import requests

from config import (
    API_BASE,
    HOTELINFOS_API,
    HOTELS_API,
    POLITE_SLEEP,
    REDIRECT_API,
    SESSION_FILE,
    build_rates_api_url,
    swap_dates,
)

DEMAND_API = f"{API_BASE}/apigateway/v1/app/demand/ari/demands/"

from refresh import refresh_and_wait  # noqa: E402  (must follow API_BASE definition)

# -------- API helpers ---------------------------------------------------


def make_session() -> requests.Session:
    """Build a requests.Session from the shared session.json cookie file."""
    s_data = json.loads(SESSION_FILE.read_text())
    s = requests.Session()
    for c in s_data["cookies"]:
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
    s.headers.update(
        {
            "User-Agent": s_data["user_agent"],
            "Accept": "application/json, text/plain, */*",
            "Origin": API_BASE,
        }
    )
    return s


def fetch_rates_range(
    sess,
    hotel_id,
    from_date,
    to_date,
    *,
    ota,
    compset_id,
    los,
    persons,
    mealtype,
    membershiptype,
    platform,
    roomtype,
    bar,
    flexible,
    rate_type,
    meta,
):
    url = build_rates_api_url(
        hotel_id,
        from_date=from_date.isoformat() if isinstance(from_date, date) else from_date,
        to_date=to_date.isoformat() if isinstance(to_date, date) else to_date,
        compset_id=compset_id,
        los=los,
        persons=persons,
        ota=ota,
        mealtype=mealtype,
        membershiptype=membershiptype,
        platform=platform,
        roomtype=roomtype,
        bar=bar,
        flexible=flexible,
        rate_type=rate_type,
        meta=meta,
    )
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


def fetch_demand(sess, hotel_id, from_date, to_date):
    """Market demand scores for a hotel over [from,to]. Returns {iso_date: pct}."""
    r = sess.get(
        DEMAND_API,
        params={
            "from_date_range_start": from_date,
            "from_date_range_end": to_date,
            "subscription_id": hotel_id,
        },
        timeout=30,
    )
    r.raise_for_status()
    out = {}
    for d in r.json().get("demands", []):
        v = d.get("value")
        if v and v > 0:
            out[d["day"]] = round(v * 100, 1)
    return out


def resolve_booking_base_url(sess, hotel_id, hotelinfo_id, seed_date, los, persons, ota):
    r = sess.get(
        REDIRECT_API,
        params={
            "ota": ota,
            "hotelId": hotelinfo_id,
            "direct": "false",
            "fromDate": seed_date,
            "los": los,
            "persons": persons,
            "city": "false",
            "subscription_id": hotel_id,
            "pos": "",
            "source": "app_rates",
        },
        allow_redirects=True,
        timeout=30,
    )
    # /redirect returns the Lighthouse URL unchanged on failure; ignore those.
    if r.url and r.url.startswith("http") and "mylighthouse.com" not in r.url:
        return r.url
    return None


def pick_primary_rate(records):
    for r in records:
        if (r.get("value") or 0) > 0:
            return r
    return records[0] if records else None


_SLIM_KEYS = [
    "value",
    "currency",
    "shop_value",
    "shop_currency",
    "room_name",
    "room_type",
    "cema_category",
    "best_flex",
    "cancellable",
    "cancellation",
    "city_tax",
    "vat",
    "other_taxes",
    "city_tax_incl",
    "vat_incl",
    "other_taxes_incl",
    "extract_datetime",
    "is_out_of_sync",
    "max_persons",
    "message",
    "platform",
    "membershiptype",
    "mealtype_included",
    "is_baserate",
    "difference_with_baserate",
]


def slim_rate(r):
    return {k: r.get(k) for k in _SLIM_KEYS if k in r}


# -------- Caches --------------------------------------------------------


@dataclass
class Caches:
    hotels: dict  # subscription_id -> /api/v3/hotels row
    hotelinfos: dict  # hotelinfo_id -> /api/v3/hotelinfos row
    booking_urls: dict  # "<subscription>:<hotelinfo>" -> OTA URL


# -------- The main entry point -------------------------------------------


def scrape_hotel(sess: requests.Session, job, hotel_id: str, caches: Caches) -> dict:
    """Execute one hotel's share of a Job and return a snapshot dict.

    The caller is responsible for locking (hotel_id, ota), persisting
    caches, and writing the snapshot.  All HTTP is done here.
    """
    scrape_date = date.today().isoformat()
    snap: dict = {
        "scrape_date": scrape_date,
        "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "job_id": job.job_id,
        "hotel_id": hotel_id,
        "ota": job.ota,
        "compset_id": job.compset_id,
        "los": job.los,
        "persons": job.persons,
        "mealtype": job.mealtype,
        "membershiptype": job.membershiptype,
        "platform": job.platform,
        "roomtype": job.roomtype,
        "bar": job.bar,
        "flexible": job.flexible,
        "rate_type": job.rate_type,
        "do_refresh": job.do_refresh,
        "refresh_only": job.refresh_only,
    }

    # --- Subscription metadata (cached) ---
    if hotel_id in caches.hotels:
        sub_meta = caches.hotels[hotel_id]
    else:
        sub_meta = fetch_subscription_meta(sess, hotel_id) or {}
        caches.hotels[hotel_id] = sub_meta
        time.sleep(POLITE_SLEEP)
    own_hi = str(sub_meta.get("hotelinfo")) if sub_meta.get("hotelinfo") else None
    snap["own_hotelinfo_id"] = own_hi

    # --- Refresh (if requested) ---
    refresh_results = []
    if job.do_refresh or job.refresh_only:
        for fd, td in job.refresh_windows():
            res = refresh_and_wait(
                sess,
                hotel_id,
                fd,
                td,
                ota=job.ota,
                compset_id=job.compset_id,
                los=job.los,
                persons=job.persons,
                mealtype=job.mealtype,
                membershiptype=job.membershiptype,
                platform=job.platform,
                roomtype=job.roomtype,
                bar=job.bar,
                flexible=job.flexible,
                rate_type=job.rate_type,
            )
            refresh_results.append(res)
    snap["refreshes"] = refresh_results

    if job.refresh_only:
        snap["total_rate_cells"] = 0
        snap["note"] = "refresh-only: rates intentionally not fetched"
        return snap

    # --- Rates fetch for the full date span, one call ---
    from_d, to_d = job.date_range()
    api_url, body = fetch_rates_range(
        sess,
        hotel_id,
        from_d,
        to_d,
        ota=job.ota,
        compset_id=job.compset_id,
        los=job.los,
        persons=job.persons,
        mealtype=job.mealtype,
        membershiptype=job.membershiptype,
        platform=job.platform,
        roomtype=job.roomtype,
        bar=job.bar,
        flexible=job.flexible,
        rate_type=job.rate_type,
        meta=job.meta,
    )
    snap["api_url"] = api_url

    # --- Market demand for the same span ---
    try:
        demand_by_date = fetch_demand(sess, hotel_id, from_d.isoformat(), to_d.isoformat())
    except Exception:
        demand_by_date = {}

    # --- Collect every competitor hotelinfo_id observed in response ---
    wanted_dates = {d.isoformat() for d in job.checkin_dates}
    all_hotelinfo_ids: set[str] = set()
    for period in body.get("periods", []):
        for hid in period.get("rates") or {}:
            all_hotelinfo_ids.add(str(hid))
    if own_hi:
        all_hotelinfo_ids.add(own_hi)

    # --- Hotelinfo metadata (cached) ---
    for hi in sorted(all_hotelinfo_ids):
        if hi not in caches.hotelinfos:
            caches.hotelinfos[hi] = fetch_hotelinfo(sess, hi) or {}
            time.sleep(POLITE_SLEEP)

    # --- OTA base URLs per (hotel, hotelinfo) (cached) ---
    # Cache key includes ota because /redirect returns different URLs per OTA.
    seed_date = next(
        (p.get("from_date") for p in body.get("periods", []) if p.get("from_date")), None
    )
    for hi in sorted(all_hotelinfo_ids):
        key = f"{hotel_id}:{hi}:{job.ota}"
        if key not in caches.booking_urls and seed_date:
            try:
                url = resolve_booking_base_url(
                    sess,
                    hotel_id,
                    hi,
                    seed_date,
                    job.los,
                    job.persons,
                    job.ota,
                )
            except Exception:
                url = None
            caches.booking_urls[key] = url
            time.sleep(POLITE_SLEEP)

    # --- Competitors block ---
    competitors = {}
    for hi in sorted(all_hotelinfo_ids):
        meta = caches.hotelinfos.get(hi, {})
        competitors[hi] = {
            "name": meta.get("name"),
            "stars": meta.get("stars"),
            "country": meta.get("country"),
            "latitude": meta.get("latitude"),
            "longitude": meta.get("longitude"),
            "hotel_group": meta.get("hotel_group"),
            "is_own": hi == own_hi,
            "booking_base_url": caches.booking_urls.get(f"{hotel_id}:{hi}:{job.ota}"),
        }
    snap["competitors"] = competitors

    # --- Rate grid, filtered to job.checkin_dates ---
    rates_list = []
    total_rates = 0
    for period in body.get("periods", []):
        d = period.get("from_date")
        if d not in wanted_dates:
            continue
        checkout = (date.fromisoformat(d) + timedelta(days=job.los)).isoformat() if d else None
        hotels_cells = {}
        for hi_id, recs in (period.get("rates") or {}).items():
            primary = pick_primary_rate(recs)
            if primary is None:
                continue
            base_url = caches.booking_urls.get(f"{hotel_id}:{hi_id}:{job.ota}")
            cell = slim_rate(primary)
            cell["booking_url"] = swap_dates(base_url, d, job.los) if base_url and d else None
            hotels_cells[str(hi_id)] = cell
            total_rates += 1
        rates_list.append(
            {
                "date": d,
                "checkout_date": checkout,
                "leadtime_days": period.get("leadtime"),
                "market_demand_pct": demand_by_date.get(d),
                "hotels": hotels_cells,
            }
        )

    snap["date_range"] = [from_d.isoformat(), to_d.isoformat()]
    snap["rates"] = rates_list
    snap["total_rate_cells"] = total_rates
    return snap
