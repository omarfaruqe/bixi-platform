"""Build the modelling table: one row per study station and season hour.

Leakage rule (docs/decisions.md, section 3), made concrete:
a forecast is issued at time T for the hours T+1 ... T+24. Every feature for target hour t must
therefore be known at t - 24 h or earlier, or be known far in advance (calendar, station
attributes, scheduled events). Concretely:

* demand lags are 24 h or older (``*_lag_24``, ``*_lag_168``, the 24-hour sum ending 24 h ago);
* weather comes from day-ahead forecasts (``fc_*``), never from what was observed (``obs_*``);
* ``obs_*`` columns are kept only for the "oracle" comparison and are listed separately.

Lags are joined on shifted timestamps, not shifted rows, so a lag never reaches across the
winter gap between seasons (it is null instead) and DST changes cannot misalign them.
"""

from __future__ import annotations

import polars as pl

from bixi.features.calendar import HOLIDAY, WEEKEND, with_day_type
from bixi.ingest.rules import SEASON_START

TARGETS = ("departures", "arrivals")
LAG_HOURS = (24, 48, 168, 336)
SAME_HOUR_WEEKS = (1, 2, 3, 4)  # mean of the same hour 1-4 weeks earlier

# Feature groups. Step 6 picks groups by name; "weather_observed" is the oracle-only group.
FEATURE_GROUPS: dict[str, list[str]] = {
    "calendar": [
        "local_hour",
        "weekday",
        "is_weekend",
        "is_holiday",
        "month",
        "day_of_season",
        "year",
    ],
    "station": ["station_id", "capacity", "lat", "lon", "volume_tier", "station_type"],
    "lags": [
        *(f"{t}_lag_{h}" for t in TARGETS for h in LAG_HOURS),
        *(f"{t}_same_hour_4w" for t in TARGETS),
        *(f"{t}_sum_24h_lag_24" for t in TARGETS),
    ],
    "system": ["system_departures_lag_24", "system_departures_lag_168"],
    "events": ["event_any", "event_distance_km"],
    "weather_forecast": [
        "fc_temperature_2m",
        "fc_apparent_temperature",
        "fc_precipitation",
        "fc_relative_humidity_2m",
        "fc_cloud_cover",
        "fc_wind_speed_10m",
        "fc_is_rainy",
    ],
    "weather_observed": [
        "obs_temperature_2m",
        "obs_apparent_temperature",
        "obs_precipitation",
        "obs_relative_humidity_2m",
        "obs_cloud_cover",
        "obs_wind_speed_10m",
        "obs_is_rainy",
    ],
}
PRODUCTION_GROUPS = ("calendar", "station", "lags", "system", "events", "weather_forecast")


def production_features() -> list[str]:
    return [f for g in PRODUCTION_GROUPS for f in FEATURE_GROUPS[g]]


def _shifted(df: pl.DataFrame, keys: list[str], column: str, hours: int, name: str) -> pl.DataFrame:
    """The value of ``column`` ``hours`` earlier, keyed on the later timestamp."""
    return df.select(
        *[k for k in keys if k != "ts_utc"],
        (pl.col("ts_utc") + pl.duration(hours=hours)).alias("ts_utc"),
        pl.col(column).alias(name),
    )


def add_lags(df: pl.DataFrame) -> pl.DataFrame:
    keys = ["station_id", "ts_utc"]
    df = df.sort(keys).with_columns(
        [
            pl.col(t)
            .cast(pl.Float64)
            .rolling_sum_by("ts_utc", window_size="24h")
            .over("station_id")
            .alias(f"_{t}_sum24")
            for t in TARGETS
        ]
    )
    for t in TARGETS:
        for h in sorted(set(LAG_HOURS) | {168 * w for w in SAME_HOUR_WEEKS}):
            df = df.join(_shifted(df, keys, t, h, f"{t}_lag_{h}"), on=keys, how="left")
        df = df.join(
            _shifted(df, keys, f"_{t}_sum24", 24, f"{t}_sum_24h_lag_24"), on=keys, how="left"
        )
        weekly = [f"{t}_lag_{168 * w}" for w in SAME_HOUR_WEEKS]
        df = df.with_columns(pl.mean_horizontal(weekly).alias(f"{t}_same_hour_4w"))
        extra = [c for c in weekly if c not in {f"{t}_lag_{h}" for h in LAG_HOURS}]
        df = df.drop(extra)
    return df.drop([f"_{t}_sum24" for t in TARGETS])


def add_system_lags(df: pl.DataFrame, system: pl.DataFrame) -> pl.DataFrame:
    for h in (24, 168):
        df = df.join(
            _shifted(system, ["ts_utc"], "system_departures", h, f"system_departures_lag_{h}"),
            on="ts_utc",
            how="left",
        )
    return df


def add_calendar(df: pl.DataFrame) -> pl.DataFrame:
    return with_day_type(df).with_columns(
        is_weekend=(pl.col("day_type") == WEEKEND).cast(pl.Int8),
        is_holiday=(pl.col("day_type") == HOLIDAY).cast(pl.Int8),
        month=pl.col("local_date").dt.month().cast(pl.Int8),
        year=pl.col("local_date").dt.year().cast(pl.Int16),
        day_of_season=(
            pl.col("local_date")
            - pl.date(pl.col("local_date").dt.year(), SEASON_START[0], SEASON_START[1])
        )
        .dt.total_days()
        .cast(pl.Int16),
    )


def build_features(
    hourly: pl.DataFrame,
    stations: pl.DataFrame,
    system: pl.DataFrame,
    observed: pl.DataFrame,
    forecast: pl.DataFrame | None,
    events: pl.DataFrame,
) -> pl.DataFrame:
    """Join every feature group onto the hourly station grid."""
    static = stations.select("station_id", "capacity", "lat", "lon", "volume_tier", "station_type")
    df = add_calendar(hourly)
    df = add_lags(df)
    df = add_system_lags(df, system)
    df = df.join(static, on="station_id", how="left")
    df = df.join(observed, on="ts_utc", how="left")
    if forecast is not None:
        df = df.join(forecast, on="ts_utc", how="left")
    else:
        df = df.with_columns(
            [pl.lit(None, dtype=pl.Float64).alias(c) for c in FEATURE_GROUPS["weather_forecast"]]
        )
    df = df.join(events, on=["station_id", "local_date"], how="left").with_columns(
        pl.col("event_any").fill_null(0)
    )
    columns = ["station_id", "ts_utc", "ts_local", "local_date", "day_type", *TARGETS]
    features = [c for g in FEATURE_GROUPS.values() for c in g if c not in columns]
    return df.select(*columns, *features).sort("station_id", "ts_utc")
