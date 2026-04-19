"""Ingest one Lighthouse snapshot dict into Postgres.

Entry point: `ingest_snapshot(snap, job_id)` — called from
snapshot.save_hotel_snapshot() after the JSON file is written.

Design contract:
  - JSON on disk is authoritative.  If ingest raises, we log and
    continue — the scrape itself is not affected.
  - Every UPSERT key is chosen so concurrent jobs on different
    (hotel, ota) pairs never collide.
  - One transaction per hotel-per-Job.  All rate rows for a hotel
    commit together or none do.
  - Idempotent: re-running the same (source, subject, competitor,
    stay_date, los, persons, observation_date) UPSERTs the row.
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from .connection import get_conn
from .mapping import (
    coerce_decimal,
    now_utc,
    parse_iso_date,
    parse_iso_dt,
    source_code_for_ota,
)
from .pricing import compute_all_in_price

_log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# public entry point
# ----------------------------------------------------------------------


def ingest_snapshot(snap: dict, job_id: str) -> int | None:
    """Persist one hotel's snapshot dict to Postgres.

    Returns the scrape_run_id on success, or None if the DB was
    unavailable / misconfigured.  Never raises — swallow-and-log
    keeps the JSON write path authoritative.
    """
    conn = get_conn()
    if conn is None:
        return None
    try:
        with conn.transaction():
            source_id = _resolve_source_id(conn, snap["ota"])
            subject_hotel_id = _resolve_subject_by_subscription(conn, snap["hotel_id"])
            scrape_run_id = _upsert_scrape_run(conn, source_id, snap, job_id)
            _upsert_raw_payload(conn, scrape_run_id, source_id, subject_hotel_id, snap)

            hi_to_pk = _upsert_hotels(conn, snap)
            own_hi = snap.get("own_hotelinfo_id")
            if not own_hi or own_hi not in hi_to_pk:
                raise RuntimeError(f"subject hotelinfo_id {own_hi!r} missing from hotels upsert")

            _upsert_compset_members(conn, subject_hotel_id, own_hi, hi_to_pk)

            total = _insert_rate_rows(
                conn,
                snap,
                scrape_run_id,
                source_id,
                subject_hotel_id,
                hi_to_pk,
            )
            _insert_scrape_run_hotel(conn, scrape_run_id, subject_hotel_id, snap, total)
        return scrape_run_id
    except Exception as e:
        _log.warning(
            "ingest_snapshot failed for hotel=%s ota=%s: %s",
            snap.get("hotel_id"),
            snap.get("ota"),
            e,
        )
        return None


# ----------------------------------------------------------------------
# step helpers
# ----------------------------------------------------------------------


def _resolve_source_id(conn, ota: str) -> int:
    code = source_code_for_ota(ota)
    with conn.cursor() as cur:
        cur.execute("SELECT source_id FROM sources WHERE source_code = %s", (code,))
        row = cur.fetchone()
        if row:
            return row[0]
        # Auto-register: the schema's "one row per source" model.
        cur.execute(
            "INSERT INTO sources (source_code, source_name) VALUES (%s, %s) RETURNING source_id",
            (code, f"{code} via Lighthouse"),
        )
        return cur.fetchone()[0]


def _upsert_scrape_run(conn, source_id: int, snap: dict, job_id: str) -> int:
    """One scrape_runs row per (source, scrape_date, job_id).

    Concurrent-safe: different jobs get different rows on the same day.
    """
    scrape_date = parse_iso_date(snap.get("scrape_date"))
    started_at = parse_iso_dt(snap.get("scraped_at")) or now_utc()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scrape_runs
                (source_id, scrape_date, scrape_job_id, started_at, status)
            VALUES (%s, %s, %s, %s, 'running')
            ON CONFLICT (source_id, scrape_date, scrape_job_id) DO UPDATE
                SET started_at = scrape_runs.started_at
            RETURNING scrape_run_id
            """,
            (source_id, scrape_date, job_id, started_at),
        )
        return cur.fetchone()[0]


def _resolve_subject_by_subscription(conn, subscription_id: str) -> int:
    """Find subject_hotel_id from the Lighthouse subscription_id (hotels.json key)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT subject_hotel_id FROM subject_hotels WHERE subscription_id = %s",
            (str(subscription_id),),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(
                f"subject_hotels row missing for subscription_id={subscription_id!r}; "
                f"run db/migrations/0009 or admin.py add"
            )
        return row[0]


def _upsert_raw_payload(
    conn, scrape_run_id: int, source_id: int, subject_hotel_id: int, snap: dict
) -> None:
    """Store the snapshot dict (same shape as the JSON file on disk).

    Idempotent on (scrape_run_id, subject_hotel_id, los, persons).
    """
    payload_bytes = json.dumps(snap, sort_keys=True, default=str).encode()
    sha = hashlib.sha256(payload_bytes).hexdigest()

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_payloads
                (scrape_run_id, subject_hotel_id, source_id, los, persons,
                 scrape_date, payload, payload_sha256)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scrape_run_id, subject_hotel_id, los, persons)
            DO UPDATE SET payload        = EXCLUDED.payload,
                          payload_sha256 = EXCLUDED.payload_sha256,
                          stored_at      = NOW()
            """,
            (
                scrape_run_id,
                subject_hotel_id,
                source_id,
                int(snap["los"]),
                int(snap["persons"]),
                parse_iso_date(snap.get("scrape_date")),
                Jsonb(snap),
                sha,
            ),
        )


def _upsert_hotels(conn, snap: dict) -> dict[str, int]:
    """Upsert subject + every competitor into `hotels`.  Returns
    {external_hotel_id: hotel_pk}."""
    out: dict[str, int] = {}
    competitors: dict[str, dict] = snap.get("competitors") or {}
    # Make sure the subject itself is in there even if not in `competitors`.
    own_hi = snap.get("own_hotelinfo_id")
    targets = dict(competitors)
    if own_hi and own_hi not in targets:
        targets[own_hi] = {"name": snap.get("hotel_id"), "is_own": True}

    with conn.cursor() as cur:
        for hi, meta in targets.items():
            cur.execute(
                """
                INSERT INTO hotels
                    (external_hotel_id, name, stars, country,
                     latitude, longitude, hotel_group, booking_base_url,
                     first_seen_at, last_seen_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (external_hotel_id) DO UPDATE
                    SET name             = COALESCE(EXCLUDED.name, hotels.name),
                        stars            = COALESCE(EXCLUDED.stars, hotels.stars),
                        country          = COALESCE(EXCLUDED.country, hotels.country),
                        latitude         = COALESCE(EXCLUDED.latitude, hotels.latitude),
                        longitude        = COALESCE(EXCLUDED.longitude, hotels.longitude),
                        hotel_group      = COALESCE(EXCLUDED.hotel_group, hotels.hotel_group),
                        booking_base_url = COALESCE(EXCLUDED.booking_base_url, hotels.booking_base_url),
                        last_seen_at     = NOW()
                RETURNING hotel_pk
                """,
                (
                    str(hi),
                    meta.get("name") or f"unknown-{hi}",
                    meta.get("stars"),
                    meta.get("country"),
                    coerce_decimal(meta.get("latitude")),
                    coerce_decimal(meta.get("longitude")),
                    meta.get("hotel_group"),
                    meta.get("booking_base_url"),
                ),
            )
            out[str(hi)] = cur.fetchone()[0]
    return out


def _upsert_compset_members(
    conn,
    subject_hotel_id: int,
    own_hi: str,
    hi_to_pk: dict[str, int],
) -> None:
    """UNION across sources — add any competitor we haven't seen active.

    Does NOT close existing active rows even if they're absent from this
    payload; different OTAs return different compset sets for some
    subjects (validated).  Manual close via admin.py close-compset-member.
    """
    with conn.cursor() as cur:
        for hi, pk in hi_to_pk.items():
            cur.execute(
                """
                INSERT INTO compset_members
                    (subject_hotel_id, competitor_hotel_pk, is_own, valid_from)
                VALUES (%s, %s, %s, CURRENT_DATE)
                ON CONFLICT (subject_hotel_id, competitor_hotel_pk, valid_from)
                DO NOTHING
                """,
                (subject_hotel_id, pk, hi == own_hi),
            )
            # Also suppress adding a row if there's already an active
            # (valid_to IS NULL) row with an earlier valid_from — we don't
            # want duplicates per day.
            cur.execute(
                """
                DELETE FROM compset_members
                 WHERE subject_hotel_id    = %s
                   AND competitor_hotel_pk = %s
                   AND valid_from          = CURRENT_DATE
                   AND EXISTS (
                       SELECT 1 FROM compset_members cm2
                        WHERE cm2.subject_hotel_id    = %s
                          AND cm2.competitor_hotel_pk = %s
                          AND cm2.valid_to IS NULL
                          AND cm2.valid_from < CURRENT_DATE
                   )
                """,
                (subject_hotel_id, pk, subject_hotel_id, pk),
            )


def _insert_rate_rows(
    conn,
    snap: dict,
    scrape_run_id: int,
    source_id: int,
    subject_hotel_id: int,
    hi_to_pk: dict[str, int],
) -> int:
    """For each (date, competitor) cell: UPSERT rate_observations + UPSERT rates_current.

    Returns the number of rate cells persisted.
    """
    los = int(snap["los"])
    persons = int(snap["persons"])
    obs_date = parse_iso_date(snap.get("scrape_date"))
    obs_ts = parse_iso_dt(snap.get("scraped_at")) or now_utc()

    rates_list = snap.get("rates") or []
    total = 0

    with conn.cursor() as cur:
        for period in rates_list:
            stay_date = parse_iso_date(period.get("date"))
            checkout_date = parse_iso_date(period.get("checkout_date"))
            leadtime_days = period.get("leadtime_days")
            demand_pct = coerce_decimal(period.get("market_demand_pct"))
            if stay_date is None:
                continue

            for hi, cell in (period.get("hotels") or {}).items():
                pk = hi_to_pk.get(str(hi))
                if pk is None:
                    continue

                row = _rate_row_values(
                    snap,
                    cell,
                    stay_date,
                    checkout_date,
                    leadtime_days,
                    demand_pct,
                    los,
                    persons,
                    obs_date,
                    obs_ts,
                    source_id,
                    subject_hotel_id,
                    pk,
                    scrape_run_id,
                )
                # Look up the prior-day rate for delta computation.
                # Reading from rate_observations (not rates_current) and
                # filtering on observation_date < today guarantees the
                # "prior" is genuinely from yesterday or earlier — never
                # from an earlier run on the same day (which would make
                # changed_from_prior a false negative on same-day retries).
                cur.execute(
                    """
                    SELECT rate_value FROM rate_observations
                     WHERE source_id            = %s
                       AND subject_hotel_id     = %s
                       AND competitor_hotel_pk  = %s
                       AND stay_date            = %s
                       AND los                  = %s
                       AND persons              = %s
                       AND observation_date     < %s
                     ORDER BY observation_date DESC
                     LIMIT 1
                    """,
                    (source_id, subject_hotel_id, pk, stay_date, los, persons, obs_date),
                )
                prior_row = cur.fetchone()
                prior_rate = prior_row[0] if prior_row else None

                new_rate: Decimal | None = row["rate_value"]
                rate_delta = None
                changed = False
                if new_rate is not None and prior_rate is not None:
                    rate_delta = new_rate - prior_rate
                    changed = rate_delta != 0
                elif new_rate != prior_rate:
                    # one is None, the other isn't — a "change" by availability flip.
                    changed = True

                _upsert_rate_observation(cur, row, prior_rate, rate_delta, changed)
                _upsert_rates_current(cur, row, changed)
                total += 1
    return total


def _rate_row_values(
    snap: dict,
    cell: dict,
    stay_date,
    checkout_date,
    leadtime_days,
    demand_pct,
    los: int,
    persons: int,
    obs_date,
    obs_ts,
    source_id: int,
    subject_hotel_id: int,
    competitor_hotel_pk: int,
    scrape_run_id: int,
) -> dict[str, Any]:
    """Flatten a cell + surrounding context into a uniform row dict."""
    rate_value = coerce_decimal(cell.get("value"))
    shop_value = coerce_decimal(cell.get("shop_value"))
    all_in_price = compute_all_in_price(cell)

    is_available = True
    msg = cell.get("message") or ""
    if not rate_value or msg in ("general.missing", "rates.soldout"):
        is_available = False

    return {
        "observation_date": obs_date,
        "observation_ts": obs_ts,
        "source_id": source_id,
        "subject_hotel_id": subject_hotel_id,
        "competitor_hotel_pk": competitor_hotel_pk,
        "stay_date": stay_date,
        "checkout_date": checkout_date,
        "los": los,
        "persons": persons,
        "rate_value": rate_value,
        "shop_value": shop_value,
        "all_in_price": all_in_price,
        "vat": coerce_decimal(cell.get("vat")),
        "vat_incl": cell.get("vat_incl"),
        "city_tax": coerce_decimal(cell.get("city_tax")),
        "city_tax_incl": cell.get("city_tax_incl"),
        "other_taxes": coerce_decimal(cell.get("other_taxes")),
        "other_taxes_incl": cell.get("other_taxes_incl"),
        "room_name": cell.get("room_name"),
        "room_type": cell.get("room_type"),
        "cema_category": cell.get("cema_category"),
        "max_persons": cell.get("max_persons"),
        "mealtype_included": cell.get("mealtype_included"),
        "membershiptype": cell.get("membershiptype"),
        "best_flex": cell.get("best_flex"),
        "cancellable": cell.get("cancellable"),
        "cancellation": cell.get("cancellation"),
        "is_baserate": cell.get("is_baserate"),
        "is_out_of_sync": cell.get("is_out_of_sync"),
        "platform": cell.get("platform"),
        "is_available": is_available,
        "booking_url": cell.get("booking_url"),
        "extract_datetime": parse_iso_dt(cell.get("extract_datetime")),
        "message": cell.get("message"),
        "leadtime_days": leadtime_days,
        "market_demand_pct": demand_pct,
        "scrape_run_id": scrape_run_id,
    }


_RO_COLS = [
    "observation_date",
    "observation_ts",
    "source_id",
    "subject_hotel_id",
    "competitor_hotel_pk",
    "stay_date",
    "checkout_date",
    "los",
    "persons",
    "rate_value",
    "shop_value",
    "all_in_price",
    "vat",
    "vat_incl",
    "city_tax",
    "city_tax_incl",
    "other_taxes",
    "other_taxes_incl",
    "room_name",
    "room_type",
    "cema_category",
    "max_persons",
    "mealtype_included",
    "membershiptype",
    "best_flex",
    "cancellable",
    "cancellation",
    "is_baserate",
    "is_out_of_sync",
    "platform",
    "is_available",
    "booking_url",
    "extract_datetime",
    "message",
    "leadtime_days",
    "market_demand_pct",
    "prior_rate_value",
    "rate_delta",
    "changed_from_prior",
    "scrape_run_id",
]


def _upsert_rate_observation(cur, row: dict, prior_rate, rate_delta, changed: bool) -> None:
    row = {
        **row,
        "prior_rate_value": prior_rate,
        "rate_delta": rate_delta,
        "changed_from_prior": changed,
    }
    placeholders = ", ".join(["%s"] * len(_RO_COLS))
    cols = ", ".join(_RO_COLS)

    # The unique index excludes observation_id (auto-generated) so we
    # target the natural key.  Same-day re-scrape overwrites.
    update_cols = [
        c
        for c in _RO_COLS
        if c
        not in (
            "observation_date",
            "source_id",
            "subject_hotel_id",
            "competitor_hotel_pk",
            "stay_date",
            "los",
            "persons",
        )
    ]
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    cur.execute(
        f"""
        INSERT INTO rate_observations ({cols})
        VALUES ({placeholders})
        ON CONFLICT
            (source_id, subject_hotel_id, competitor_hotel_pk,
             stay_date, los, persons, observation_date)
        DO UPDATE SET {update_clause}
        """,
        [row[c] for c in _RO_COLS],
    )


_RC_NATURAL = (
    "source_id",
    "subject_hotel_id",
    "competitor_hotel_pk",
    "stay_date",
    "los",
    "persons",
)

_RC_DATA_COLS = [
    "checkout_date",
    "rate_value",
    "shop_value",
    "all_in_price",
    "vat",
    "vat_incl",
    "city_tax",
    "city_tax_incl",
    "other_taxes",
    "other_taxes_incl",
    "room_name",
    "room_type",
    "cema_category",
    "max_persons",
    "mealtype_included",
    "membershiptype",
    "best_flex",
    "cancellable",
    "cancellation",
    "is_baserate",
    "is_out_of_sync",
    "platform",
    "is_available",
    "booking_url",
    "extract_datetime",
    "message",
    "leadtime_days",
    "market_demand_pct",
    "scrape_run_id",
]


def _upsert_rates_current(cur, row: dict, changed: bool) -> None:
    now = row["observation_ts"]
    cols = (
        list(_RC_NATURAL)
        + _RC_DATA_COLS
        + ["first_observed_at", "last_scraped_at", "last_changed_at"]
    )
    values = [row[c] for c in _RC_NATURAL] + [row[c] for c in _RC_DATA_COLS] + [now, now, now]
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)

    # Update every data column; first_observed_at sticks; last_changed_at
    # only advances on a real change.
    update_clauses = [f"{c} = EXCLUDED.{c}" for c in _RC_DATA_COLS]
    update_clauses.append("last_scraped_at = EXCLUDED.last_scraped_at")
    if changed:
        update_clauses.append("last_changed_at = EXCLUDED.last_changed_at")
    update_clause = ", ".join(update_clauses)

    cur.execute(
        f"""
        INSERT INTO rates_current ({col_list})
        VALUES ({placeholders})
        ON CONFLICT ({", ".join(_RC_NATURAL)})
        DO UPDATE SET {update_clause}
        """,
        values,
    )


def _insert_scrape_run_hotel(
    conn, scrape_run_id: int, subject_hotel_id: int, snap: dict, rates_count: int
) -> None:
    # Grab duration from refreshes if present, else None.
    refreshes = snap.get("refreshes") or []
    total_refresh_s = sum((r.get("duration_s") or 0) for r in refreshes) or None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scrape_run_hotels
                (scrape_run_id, subject_hotel_id, los, persons,
                 status, duration_s, rates_count, months_scraped, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scrape_run_id, subject_hotel_id, los, persons)
            DO UPDATE SET status        = EXCLUDED.status,
                          duration_s    = EXCLUDED.duration_s,
                          rates_count   = EXCLUDED.rates_count,
                          months_scraped= EXCLUDED.months_scraped
            """,
            (
                scrape_run_id,
                subject_hotel_id,
                int(snap["los"]),
                int(snap["persons"]),
                "ok",
                total_refresh_s,
                rates_count,
                _month_list_from_range(snap.get("date_range")),
                None,
            ),
        )


def _month_list_from_range(date_range) -> list[str] | None:
    """Return distinct YYYY-MM months touched by [from, to]."""
    if not date_range:
        return None
    start = parse_iso_date(date_range[0])
    end = parse_iso_date(date_range[1])
    if not start or not end:
        return None
    months: list[str] = []
    y, m = start.year, start.month
    last = (end.year, end.month)
    while (y, m) <= last:
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y += 1
            m = 1
    return months
