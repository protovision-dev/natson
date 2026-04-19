"""Shared configuration, rolling-month math, and URL generation.

All scripts in scraper/ import from here instead of hardcoding paths,
endpoints, or date logic.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

# ---------- paths ----------

SCRAPER_DIR = Path(__file__).parent
OUT_DIR = Path(os.environ.get("OUT_DIR", SCRAPER_DIR / "output"))
SESSION_FILE = OUT_DIR / "session.json"
HOTELS_FILE = Path(os.environ.get("HOTELS_FILE", SCRAPER_DIR / "hotels.json"))
CACHE_DIR = OUT_DIR / "cache"
SNAPSHOTS_DIR = OUT_DIR / "snapshots"

# ---------- endpoints ----------

API_BASE = "https://app.mylighthouse.com"
RATES_API = f"{API_BASE}/apigateway/v1/app/rates/"
HOTELS_API = f"{API_BASE}/api/v3/hotels/"
HOTELINFOS_API = f"{API_BASE}/api/v3/hotelinfos/"
REDIRECT_API = f"{API_BASE}/redirect"
LIVEUPDATES_API = f"{API_BASE}/api/v3/liveupdates/"

BROWSER_API = os.environ.get("BROWSER_API", "http://localhost:8765")

# ---------- pacing ----------

POLITE_SLEEP = float(os.environ.get("POLITE_SLEEP", "0.25"))
REFRESH_POLL_INTERVAL_S = int(os.environ.get("REFRESH_POLL_INTERVAL_S", "15"))
REFRESH_POLL_TIMEOUT_S = int(os.environ.get("REFRESH_POLL_TIMEOUT_S", "300"))


# ---------- rolling months ----------


def rolling_months(months_ahead: int = 2) -> list[str]:
    """Current month + next `months_ahead` months as YYYY-MM strings.

    Apr 16 with months_ahead=2 → ['2026-04', '2026-05', '2026-06']
    May 1  with months_ahead=2 → ['2026-05', '2026-06', '2026-07']
    """
    today = date.today()
    result = []
    y, m = today.year, today.month
    for _ in range(months_ahead + 1):
        result.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


# ---------- URL generation ----------


def build_rates_page_url(
    hotel_id: str, month: str, compset_id: int = 1, los: int = 7, persons: int = 2
) -> str:
    """Lighthouse frontend rates page URL (what a human visits)."""
    return (
        f"{API_BASE}/hotel/{hotel_id}/rates?"
        f"compsetId={compset_id}&los={los}&maxPersons={persons}"
        f"&month={month}&view=table"
    )


def month_range(month: str) -> tuple[str, str]:
    """First and last day of YYYY-MM. No calendar-grid padding."""
    year, mo = map(int, month.split("-"))
    first = date(year, mo, 1)
    next_month = date(year + 1, 1, 1) if mo == 12 else date(year, mo + 1, 1)
    last = next_month - timedelta(days=1)
    return first.isoformat(), last.isoformat()


# Keep the old name as an alias in case anything references it.
grid_range = month_range


def build_rates_api_url(
    hotel_id: str,
    month: str | None = None,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    compset_id: int = 1,
    los: int = 7,
    persons: int = 2,
    ota: str = "bookingdotcom",
    mealtype: int = 0,
    membershiptype: int = 0,
    platform: int = -1,
    roomtype: str = "all",
    bar: bool = True,
    flexible: bool = True,
    rate_type: int = 0,
    meta: str = "nested",
) -> str:
    """Lighthouse backend rates API URL.

    Supply either `month='YYYY-MM'` (legacy, expands to its full range) or
    explicit `from_date` + `to_date` (preferred for Job-driven scrapes
    where the window is arbitrary).
    """
    if month is not None:
        start, end = grid_range(month)
    else:
        if not (from_date and to_date):
            raise ValueError("provide `month` or both `from_date`+`to_date`")
        start, end = from_date, to_date

    return f"{RATES_API}?{
        urlencode(
            {
                'ota': ota,
                'los': los,
                'mealtype': mealtype,
                'persons': persons,
                'roomtype': roomtype,
                'membershiptype': membershiptype,
                'compset_ids': compset_id,
                'platform': platform,
                'meta': meta,
                'bar': 'true' if bar else 'false',
                'flexible': 'true' if flexible else 'false',
                'rate_type': rate_type,
                'from_date_range_start': start,
                'from_date_range_end': end,
                'hotel_id': hotel_id,
            }
        )
    }"


def swap_dates(final_url: str, checkin: str, los: int) -> str:
    """Replace checkin/checkout query params on a Booking.com URL."""
    from urllib.parse import parse_qsl, urlsplit, urlunsplit

    parts = urlsplit(final_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["checkin"] = checkin
    q["checkout"] = (date.fromisoformat(checkin) + timedelta(days=los)).isoformat()
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


# ---------- hotels.json ----------


def load_hotels_config(path: Path | None = None) -> dict:
    """Load and return the hotels.json config."""
    p = path or HOTELS_FILE
    return json.loads(p.read_text())


def build_targets(config: dict | None = None, hotel_ids: list[str] | None = None) -> list[dict]:
    """From hotels.json, produce a flat list of (hotel, month) targets.

    If hotel_ids is provided, only include those hotels (for Phase 1 single-
    hotel testing).
    """
    if config is None:
        config = load_hotels_config()
    defaults = config.get("defaults", {})
    targets = []
    for hotel in config["hotels"]:
        hid = hotel["hotel_id"]
        if hotel_ids and hid not in hotel_ids:
            continue
        name = hotel["name"]
        compset_id = hotel.get("compset_id", defaults.get("compset_id", 1))
        los = hotel.get("los", defaults.get("los", 7))
        persons = hotel.get("persons", defaults.get("persons", 2))
        ota = hotel.get("ota", defaults.get("ota", "bookingdotcom"))
        months_ahead = hotel.get("months_ahead", defaults.get("months_ahead", 2))
        months = rolling_months(months_ahead)
        for month in months:
            targets.append(
                {
                    "hotel_id": hid,
                    "hotel_name": name,
                    "month": month,
                    "compset_id": compset_id,
                    "los": los,
                    "persons": persons,
                    "ota": ota,
                    "page_url": build_rates_page_url(hid, month, compset_id, los, persons),
                    "api_url": build_rates_api_url(hid, month, compset_id, los, persons, ota),
                }
            )
    return targets
