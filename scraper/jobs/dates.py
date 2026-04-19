"""Parse the --dates CLI expression into a concrete list of check-in dates,
and split long runs into ≤31-day windows suitable for /liveshop POSTs.

Supported syntaxes:
    2026-05-15                     one check-in date
    2026-05-01:2026-05-31          inclusive date range
    2026-05                        whole month (1st through last)
    2026-05:2026-07                month range, inclusive on both ends
    rolling:3                      current month + next N months

The parser returns a sorted, de-duplicated list[date].
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")
_ROLLING = re.compile(r"^rolling:(\d+)$")


def _first_of_next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _month_last_day(year: int, month: int) -> date:
    return _first_of_next_month(date(year, month, 1)) - timedelta(days=1)


def _month_bounds(month_str: str) -> tuple[date, date]:
    y, m = (int(p) for p in month_str.split("-"))
    return date(y, m, 1), _month_last_day(y, m)


def parse_dates(expr: str, today: date | None = None) -> list[date]:
    """Expand a --dates expression into a sorted list of check-in dates."""
    expr = expr.strip()
    today = today or date.today()

    # rolling:N
    m = _ROLLING.match(expr)
    if m:
        n = int(m.group(1))
        start, _ = _month_bounds(f"{today.year:04d}-{today.month:02d}")
        end = start
        y, mo = start.year, start.month
        for _ in range(n):
            mo += 1
            if mo > 12:
                mo = 1
                y += 1
        end = _month_last_day(y, mo)
        return _range(start, end)

    # Range form: "A:B"
    if ":" in expr:
        left, right = expr.split(":", 1)
        start = _as_date(left, which="start")
        end = _as_date(right, which="end")
        if end < start:
            raise ValueError(f"--dates range is inverted: {expr}")
        return _range(start, end)

    # Single YYYY-MM-DD
    if _DATE.match(expr):
        d = date.fromisoformat(expr)
        return [d]

    # Single YYYY-MM
    if _MONTH.match(expr):
        a, b = _month_bounds(expr)
        return _range(a, b)

    raise ValueError(f"--dates not recognized: {expr!r}")


def _as_date(token: str, which: str) -> date:
    """Resolve one side of a range: a date stays as-is; a month becomes its
    first or last day depending on side."""
    if _DATE.match(token):
        return date.fromisoformat(token)
    if _MONTH.match(token):
        a, b = _month_bounds(token)
        return a if which == "start" else b
    raise ValueError(f"--dates range endpoint not recognized: {token!r}")


def _range(start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


def split_into_refresh_windows(
    dates: list[date],
    max_days: int = 31,
) -> list[tuple[date, date]]:
    """Chunk a sorted date list into contiguous windows of at most max_days.

    Lighthouse's /liveshop POST rejects windows >31 days.  The output is a
    list of (from_date, to_date) inclusive tuples; each tuple becomes one
    /liveshop POST.  Gaps in the input produce separate windows too.
    """
    if not dates:
        return []
    ds = sorted(set(dates))
    windows: list[tuple[date, date]] = []
    run_start = ds[0]
    prev = ds[0]
    for d in ds[1:]:
        # break a new window if gap > 1 day OR current window would exceed max_days
        if (d - prev).days > 1 or (d - run_start).days + 1 > max_days:
            windows.append((run_start, prev))
            run_start = d
        prev = d
    windows.append((run_start, prev))
    return windows
