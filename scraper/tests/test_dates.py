"""Coverage for the --dates expression parser."""

from datetime import date

import pytest

from jobs.dates import parse_dates, split_into_refresh_windows


class TestParseDates:
    def test_single_date(self):
        assert parse_dates("2026-05-15") == [date(2026, 5, 15)]

    def test_date_range(self):
        out = parse_dates("2026-05-01:2026-05-03")
        assert out == [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3)]

    def test_full_month(self):
        out = parse_dates("2026-04")
        assert out[0] == date(2026, 4, 1)
        assert out[-1] == date(2026, 4, 30)
        assert len(out) == 30

    def test_month_range_inclusive(self):
        out = parse_dates("2026-04:2026-05")
        # April (30) + May (31)
        assert len(out) == 30 + 31
        assert out[0] == date(2026, 4, 1)
        assert out[-1] == date(2026, 5, 31)

    def test_rolling_uses_today_anchor(self):
        out = parse_dates("rolling:1", today=date(2026, 4, 19))
        # current month + next 1 → 4/1 through 5/31
        assert out[0] == date(2026, 4, 1)
        assert out[-1] == date(2026, 5, 31)

    def test_rolling_zero(self):
        out = parse_dates("rolling:0", today=date(2026, 4, 19))
        assert out[0] == date(2026, 4, 1)
        assert out[-1] == date(2026, 4, 30)

    def test_inverted_range_raises(self):
        with pytest.raises(ValueError, match="inverted"):
            parse_dates("2026-05-31:2026-05-01")

    def test_unknown_form_raises(self):
        with pytest.raises(ValueError, match="not recognized"):
            parse_dates("yesterday")


class TestSplitIntoRefreshWindows:
    def test_empty(self):
        assert split_into_refresh_windows([]) == []

    def test_contiguous_under_cap(self):
        days = [date(2026, 4, 1) + __import__("datetime").timedelta(days=i) for i in range(10)]
        assert split_into_refresh_windows(days, max_days=31) == [
            (date(2026, 4, 1), date(2026, 4, 10))
        ]

    def test_splits_at_31_day_cap(self):
        td = __import__("datetime").timedelta
        days = [date(2026, 4, 1) + td(days=i) for i in range(45)]
        windows = split_into_refresh_windows(days, max_days=31)
        assert len(windows) == 2
        assert windows[0] == (date(2026, 4, 1), date(2026, 5, 1))
        assert windows[1] == (date(2026, 5, 2), date(2026, 5, 15))

    def test_breaks_on_gap(self):
        days = [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 10), date(2026, 4, 11)]
        windows = split_into_refresh_windows(days)
        assert windows == [
            (date(2026, 4, 1), date(2026, 4, 2)),
            (date(2026, 4, 10), date(2026, 4, 11)),
        ]
