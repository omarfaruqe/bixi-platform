"""Québec calendar: statutory holidays and day types.

Holidays follow Québec's *Loi sur les normes du travail* plus Canada Day. Good Friday and
Easter Monday are both flagged: Québec employers choose one, and both shift commuting.
Federal-only days (Truth and Reconciliation, Remembrance Day) are not provincial holidays and
are left as ordinary days; Step 5 can test them as separate features.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

WEEKDAY = "weekday"
WEEKEND = "weekend"
HOLIDAY = "holiday"
DAY_TYPES = (WEEKDAY, WEEKEND, HOLIDAY)


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous algorithm, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def _nth_monday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7 + 7 * (n - 1))


def quebec_holidays(year: int) -> dict[date, str]:
    """Statutory holidays observed in Montréal, keyed by date (English names)."""
    easter = easter_sunday(year)
    may_25 = date(year, 5, 25)
    patriots = may_25 - timedelta(days=may_25.weekday() or 7)  # the Monday before May 25
    return {
        date(year, 1, 1): "New Year's Day",
        easter - timedelta(days=2): "Good Friday",
        easter + timedelta(days=1): "Easter Monday",
        patriots: "National Patriots' Day",
        date(year, 6, 24): "Fête nationale",
        date(year, 7, 1): "Canada Day",
        _nth_monday(year, 9, 1): "Labour Day",
        _nth_monday(year, 10, 2): "Thanksgiving",
        date(year, 12, 25): "Christmas Day",
    }


def holiday_dates(years: tuple[int, ...] | list[int]) -> list[date]:
    return sorted(d for y in years for d in quebec_holidays(y))


def with_day_type(df: pl.DataFrame | pl.LazyFrame, local_col: str = "ts_local"):
    """Add ``local_date``, ``local_hour``, ``weekday`` (0 = Monday) and ``day_type`` columns."""
    years = list(range(2015, 2031))
    holidays = pl.Series("h", holiday_dates(years), dtype=pl.Date)
    ts = pl.col(local_col)
    return df.with_columns(
        local_date=ts.dt.date(),
        local_hour=ts.dt.hour().cast(pl.Int8),
        weekday=(ts.dt.weekday() - 1).cast(pl.Int8),
    ).with_columns(
        day_type=pl.when(pl.col("local_date").is_in(holidays.implode()))
        .then(pl.lit(HOLIDAY))
        .when(pl.col("weekday") >= 5)
        .then(pl.lit(WEEKEND))
        .otherwise(pl.lit(WEEKDAY))
    )
