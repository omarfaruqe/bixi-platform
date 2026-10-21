"""Trip-pattern aggregations over ``hourly_station.parquet``.

Every "average" here is an average per **day** of the summed selection: when several stations are
selected their counts are added first, then averaged over the days in the filter. Because the
hourly table is a complete grid (zeros kept), dividing by days is exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import polars as pl

from bixi.features.calendar import with_day_type
from bixi.ingest.rules import SEASON_START

# Time-of-day windows used by the map and the station table (local hours, end exclusive).
WINDOWS: dict[str, tuple[int, int]] = {
    "all_day": (0, 24),
    "morning_peak": (7, 10),
    "evening_peak": (16, 19),
}


def prepare(hourly: pl.DataFrame) -> pl.DataFrame:
    """Add local calendar columns once, when the table is loaded."""
    return with_day_type(hourly).with_columns(
        year=pl.col("local_date").dt.year().cast(pl.Int16),
        month=pl.col("local_date").dt.month().cast(pl.Int8),
        net_flow=pl.col("arrivals").cast(pl.Int32) - pl.col("departures").cast(pl.Int32),
    )


def apply_filters(
    df: pl.DataFrame,
    station_ids: Sequence[str] | None = None,
    years: Sequence[int] | None = None,
    day_types: Sequence[str] | None = None,
) -> pl.DataFrame:
    if station_ids:
        df = df.filter(pl.col("station_id").is_in(list(station_ids)))
    if years:
        df = df.filter(pl.col("year").is_in(list(years)))
    if day_types:
        df = df.filter(pl.col("day_type").is_in(list(day_types)))
    return df


def _per_day_hour(df: pl.DataFrame) -> pl.DataFrame:
    """Sum the selected stations into one count per local date and hour."""
    return df.group_by("local_date", "local_hour", "weekday").agg(
        pl.col("departures", "arrivals", "net_flow").sum()
    )


def hourly_profile(df: pl.DataFrame) -> pl.DataFrame:
    """Mean departures, arrivals and net flow per local hour (0-23)."""
    return (
        _per_day_hour(df)
        .group_by("local_hour")
        .agg(pl.col("departures", "arrivals", "net_flow").mean())
        .sort("local_hour")
    )


def weekday_hour_matrix(df: pl.DataFrame) -> pl.DataFrame:
    """Mean departures per weekday (0 = Monday) and hour; long format."""
    return (
        _per_day_hour(df)
        .group_by("weekday", "local_hour")
        .agg(pl.col("departures").mean())
        .sort("weekday", "local_hour")
    )


def daily_series(df: pl.DataFrame, smooth_days: int = 7) -> pl.DataFrame:
    """Daily departures per year, aligned on day of season, with a centred rolling mean."""
    daily = (
        df.group_by("year", "local_date")
        .agg(pl.col("departures").sum())
        .sort("year", "local_date")
        .with_columns(
            season_day=(
                pl.col("local_date") - pl.date(pl.col("year"), SEASON_START[0], SEASON_START[1])
            ).dt.total_days(),
            smoothed=pl.col("departures")
            .rolling_mean(smooth_days, center=True, min_samples=1)
            .over("year"),
        )
    )
    return daily


def monthly_totals(df: pl.DataFrame) -> pl.DataFrame:
    """Total departures per year and month. Partial months (April, November) are flagged."""
    return (
        df.group_by("year", "month")
        .agg(pl.col("departures").sum(), pl.col("local_date").n_unique().alias("days"))
        .with_columns(per_day=pl.col("departures") / pl.col("days"))
        .sort("year", "month")
    )


def station_flows(df: pl.DataFrame, window: str = "all_day") -> pl.DataFrame:
    """Per station: mean daily departures, arrivals and net flow inside a time window."""
    start, end = WINDOWS[window]
    days = df.select(pl.col("local_date").n_unique()).item() or 1
    return (
        df.filter(pl.col("local_hour").is_between(start, end - 1))
        .group_by("station_id")
        .agg(pl.col("departures", "arrivals", "net_flow").sum() / days)
        .with_columns(total=pl.col("departures") + pl.col("arrivals"))
        .sort("net_flow")
    )


@dataclass(frozen=True)
class Headline:
    total_departures: int
    days: int
    mean_daily_departures: float
    busiest_hour: int
    weekend_share_of_days: float
    weekend_ratio: float  # mean weekend-day departures / mean weekday departures


def headline(df: pl.DataFrame) -> Headline | None:
    if df.is_empty():
        return None
    per_day = df.group_by("local_date", "day_type").agg(pl.col("departures").sum())
    days = per_day.height
    by_type = dict(per_day.group_by("day_type").agg(pl.col("departures").mean()).iter_rows())
    profile = hourly_profile(df)
    weekday_mean = by_type.get("weekday")
    weekend_mean = by_type.get("weekend")
    return Headline(
        total_departures=int(per_day["departures"].sum()),
        days=days,
        mean_daily_departures=float(per_day["departures"].mean()),
        busiest_hour=int(profile.sort("departures", descending=True)["local_hour"][0]),
        weekend_share_of_days=per_day.filter(pl.col("day_type") == "weekend").height / days,
        weekend_ratio=(weekend_mean / weekday_mean) if weekday_mean and weekend_mean else 0.0,
    )
