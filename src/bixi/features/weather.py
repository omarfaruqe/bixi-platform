"""Hourly weather features from Open-Meteo (UTC timestamps).

Two sources, kept apart on purpose (docs/decisions.md, leakage rule):

* ``obs_*``: observed weather (ERA5 archive). What actually happened. Using it to forecast the
  next 24 hours leaks the future, so it is only allowed in the "oracle" comparison that shows
  how much perfect weather knowledge would be worth.
* ``fc_*``: archived **day-ahead forecasts** (Previous Runs API, ``*_previous_day1``): the value
  forecast about 24 hours before each hour. This is what a real forecaster would have had, and
  it is what the production model uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

# Variables used as features, in both sources. Names are Open-Meteo's.
VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "relative_humidity_2m",
    "cloud_cover",
    "wind_speed_10m",
)
FORECAST_SUFFIX = "_previous_day1"
RAIN_THRESHOLD_MM = 0.2  # an hour counts as rainy from this much precipitation


def _read_hourly(path: Path) -> pl.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("utc_offset_seconds", 0) != 0:
        raise ValueError(f"{path.name}: expected UTC timestamps (timezone=UTC in the request)")
    hourly = payload["hourly"]
    return pl.DataFrame(hourly, strict=False).with_columns(
        ts_utc=pl.col("time")
        .str.to_datetime("%Y-%m-%dT%H:%M", time_unit="ms")
        .dt.replace_time_zone("UTC")
    )


def _derive(df: pl.DataFrame, prefix: str) -> pl.DataFrame:
    """Add a rain flag; precipitation is what riders react to most."""
    return df.with_columns(
        (pl.col(f"{prefix}precipitation") >= RAIN_THRESHOLD_MM)
        .cast(pl.Int8)
        .alias(f"{prefix}is_rainy")
    )


def observed_weather(paths: list[Path]) -> pl.DataFrame:
    """ERA5 archive files -> ts_utc + obs_<variable> columns."""
    frames = [
        _read_hourly(p).select("ts_utc", *[pl.col(v).cast(pl.Float64) for v in VARIABLES])
        for p in sorted(paths)
    ]
    df = pl.concat(frames).unique("ts_utc", keep="last").sort("ts_utc")
    return _derive(df.rename({v: f"obs_{v}" for v in VARIABLES}), "obs_")


def forecast_weather(paths: list[Path]) -> pl.DataFrame:
    """Previous Runs API files -> ts_utc + fc_<variable> columns (day-ahead forecasts)."""
    frames = []
    for path in sorted(paths):
        df = _read_hourly(path)
        columns = [
            f"{v}{FORECAST_SUFFIX}" for v in VARIABLES if f"{v}{FORECAST_SUFFIX}" in df.columns
        ]
        # A variable the archive has no data for comes back all-null (dtype Null); cast so a
        # partial year (2023: temperature only) stacks with complete years.
        frames.append(df.select("ts_utc", *[pl.col(c).cast(pl.Float64) for c in columns]))
    df = pl.concat(frames, how="diagonal").unique("ts_utc", keep="last").sort("ts_utc")
    renamed = df.rename(
        {c: "fc_" + c.removesuffix(FORECAST_SUFFIX) for c in df.columns if c != "ts_utc"}
    )
    for v in VARIABLES:  # a variable the model did not provide becomes an all-null column
        if f"fc_{v}" not in renamed.columns:
            renamed = renamed.with_columns(pl.lit(None, dtype=pl.Float64).alias(f"fc_{v}"))
    return _derive(renamed.cast({f"fc_{v}": pl.Float64 for v in VARIABLES}), "fc_")
