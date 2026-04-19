"""Job data shape and (de)serialization.

A Job captures every tunable parameter for a scrape — subscriptions,
check-in dates, URL parameters, and refresh mode.  It is serializable
as JSON (for reproducibility and for future Metabase-triggered runs).

Defaults are loaded from scraper/scraper.config.yml.  CLI overrides
stack on top via Job.from_cli.
"""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from .dates import parse_dates, split_into_refresh_windows
from .hotels import resolve_hotels

CONFIG_PATH = Path(__file__).resolve().parent.parent / "scraper.config.yml"


def _config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


@dataclass
class Job:
    job_id: str
    created_at: str
    hotels: list[str]  # resolved subscription IDs
    checkin_dates: list[date]  # resolved list, sorted
    # URL parameters
    ota: str
    los: int
    persons: int
    compset_id: int
    mealtype: int
    membershiptype: int
    platform: int
    roomtype: str
    bar: bool
    flexible: bool
    rate_type: int
    meta: str
    # Behavior
    do_refresh: bool
    refresh_only: bool = False
    # Raw inputs (for reproducibility)
    raw_hotels_expr: str = ""
    raw_dates_expr: str = ""

    # ---- factories --------------------------------------------------

    @classmethod
    def from_cli(cls, args: argparse.Namespace) -> Job:
        cfg = _config()
        u = cfg["url_params"]
        r = cfg["refresh"]

        hotels = resolve_hotels(args.hotels)
        checkins = parse_dates(args.dates or cfg["dates"]["default"])

        # Refresh flags: --refresh / --no-refresh / --refresh-only
        if args.refresh_only:
            do_refresh, refresh_only = True, True
        elif args.refresh is True:
            do_refresh, refresh_only = True, False
        elif args.refresh is False:
            do_refresh, refresh_only = False, False
        else:
            do_refresh, refresh_only = _bool(r.get("enabled", True)), False

        return cls(
            job_id=args.job_id or _new_job_id(),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            hotels=hotels,
            checkin_dates=checkins,
            ota=args.ota or u["ota"],
            los=int(args.los) if args.los is not None else int(u["los"]),
            persons=int(args.persons) if args.persons is not None else int(u["persons"]),
            compset_id=int(args.compset_id)
            if args.compset_id is not None
            else int(u["compset_id"]),
            mealtype=int(args.mealtype) if args.mealtype is not None else int(u["mealtype"]),
            membershiptype=int(args.membershiptype)
            if args.membershiptype is not None
            else int(u["membershiptype"]),
            platform=int(args.platform) if args.platform is not None else int(u["platform"]),
            roomtype=args.roomtype or u["roomtype"],
            bar=_bool(u["bar"]) if args.bar is None else _bool(args.bar),
            flexible=_bool(u["flexible"]) if args.flexible is None else _bool(args.flexible),
            rate_type=int(args.rate_type) if args.rate_type is not None else int(u["rate_type"]),
            meta=args.meta or u["meta"],
            do_refresh=do_refresh,
            refresh_only=refresh_only,
            raw_hotels_expr=args.hotels,
            raw_dates_expr=args.dates or cfg["dates"]["default"],
        )

    @classmethod
    def from_file(cls, path: Path) -> Job:
        data = json.loads(Path(path).read_text())
        data["checkin_dates"] = [date.fromisoformat(d) for d in data["checkin_dates"]]
        return cls(**data)

    # ---- helpers ----------------------------------------------------

    def refresh_windows(self, max_days: int | None = None) -> list[tuple[date, date]]:
        """Contiguous ≤max_days chunks of checkin_dates, for /liveshop POSTs."""
        if max_days is None:
            max_days = int(_config()["refresh"]["max_window_days"])
        return split_into_refresh_windows(self.checkin_dates, max_days=max_days)

    def date_range(self) -> tuple[date, date]:
        return (self.checkin_dates[0], self.checkin_dates[-1])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checkin_dates"] = [cd.isoformat() for cd in self.checkin_dates]
        return d

    def write(self, out_dir: Path) -> Path:
        """Write a reproducible spec.json for this job."""
        d = out_dir / "jobs" / self.job_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / "spec.json"
        p.write_text(json.dumps(self.to_dict(), indent=2))
        return p


def _new_job_id() -> str:
    # Short, sortable, no slashes — safe for filenames.
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def add_cli_args(parser: argparse.ArgumentParser) -> None:
    """Attach every Job-related flag to an argparse parser.

    Defaults are all None so that Job.from_cli can tell whether the user
    supplied them (use the flag) or not (fall back to scraper.config.yml).
    """
    parser.add_argument(
        "--hotels", required=True, help="Comma-separated hotel_ids, `portfolio`, or file:path.json"
    )
    parser.add_argument(
        "--dates",
        default=None,
        help="YYYY-MM-DD | YYYY-MM-DD:YYYY-MM-DD | YYYY-MM | YYYY-MM:YYYY-MM | rolling:N",
    )
    parser.add_argument("--ota", default=None, help="bookingdotcom | branddotcom | …")
    parser.add_argument("--los", type=int, default=None, help="Length of stay (nights)")
    parser.add_argument("--persons", type=int, default=None)
    parser.add_argument("--compset-id", dest="compset_id", type=int, default=None)
    parser.add_argument("--mealtype", type=int, default=None)
    parser.add_argument("--membershiptype", type=int, default=None)
    parser.add_argument("--platform", type=int, default=None)
    parser.add_argument("--roomtype", default=None)
    parser.add_argument("--bar", default=None, help="true/false")
    parser.add_argument("--flexible", default=None, help="true/false")
    parser.add_argument("--rate-type", dest="rate_type", type=int, default=None)
    parser.add_argument("--meta", default=None)
    # Refresh mode: tri-state --refresh / --no-refresh / --refresh-only
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--refresh",
        dest="refresh",
        action="store_true",
        default=None,
        help="Trigger /liveshop + poll, then fetch rates (default from config)",
    )
    refresh_group.add_argument(
        "--no-refresh",
        dest="refresh",
        action="store_false",
        help="Skip refresh, only fetch rates against whatever is cached",
    )
    refresh_group.add_argument(
        "--refresh-only",
        dest="refresh_only",
        action="store_true",
        default=False,
        help="Trigger refresh but skip the rate fetch (warm-up mode)",
    )
    parser.add_argument(
        "--job-id", dest="job_id", default=None, help="Override job_id; default is timestamp-uuid6"
    )
