"""Snapshot → row-shape helpers.

Translates the scraper's OTA codes into `sources.source_code`, and
normalizes per-cell / per-competitor fields into tuples ready to hand
to psycopg.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any


# Lighthouse uses `bookingdotcom` / `branddotcom`.
# The DB `sources.source_code` values are `booking` / `brand`.
OTA_TO_SOURCE_CODE: dict[str, str] = {
    "bookingdotcom": "booking",
    "branddotcom":   "brand",
}


def source_code_for_ota(ota: str) -> str:
    """Return the DB source_code for a Lighthouse OTA.

    Falls back to the OTA string itself (minus the trailing `dotcom`)
    if unknown — preserves the schema's "new sources are one row" model
    without requiring a code change to add one.
    """
    if ota in OTA_TO_SOURCE_CODE:
        return OTA_TO_SOURCE_CODE[ota]
    if ota.endswith("dotcom"):
        return ota[: -len("dotcom")]
    return ota


def parse_iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Lighthouse sometimes uses trailing 'Z' without +00:00.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def coerce_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
