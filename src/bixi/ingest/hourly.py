"""Hourly departure and arrival counts on a complete station x hour grid.

Hours with no trips are real zeros and must be present: a model trained only on non-empty hours
would never learn that quiet hours exist. Hours are UTC; ``ts_local`` is derived for features.
"""

from __future__ import annotations

import polars as pl

from bixi.ingest.rules import LOCAL_TZ, season_bounds_utc

HOUR = "1h"


def season_hours(year: int) -> pl.DataFrame:
    """Every UTC hour in the season of ``year``. DST days have 23 or 25 local hours."""
    start, end = season_bounds_utc(year)
    hours = pl.datetime_range(
        start, end, interval=HOUR, closed="left", time_unit="ms", time_zone="UTC", eager=True
    )
    return pl.DataFrame({"ts_utc": hours})


def _counts(clean: pl.LazyFrame, kind: str) -> pl.LazyFrame:
    station, ts, flag, name = {
        "departures": ("start_station_id", "start_utc", "is_departure", "departures"),
        "arrivals": ("end_station_id", "end_utc", "is_arrival", "arrivals"),
    }[kind]
    return (
        clean.filter(pl.col(flag) & pl.col(station).is_not_null())
        .group_by(
            pl.col(station).alias("station_id"),
            pl.col(ts).dt.truncate(HOUR).alias("ts_utc"),
        )
        .agg(pl.len().cast(pl.UInt32).alias(name))
    )


def hourly_station_counts(clean: pl.LazyFrame, station_ids: list[str], year: int) -> pl.DataFrame:
    """Departures and arrivals for each study station in every season hour of ``year``."""
    grid = (
        pl.DataFrame({"station_id": sorted(station_ids)})
        .join(season_hours(year), how="cross")
        .lazy()
    )
    selected = clean.filter(
        pl.col("start_station_id").is_in(station_ids) | pl.col("end_station_id").is_in(station_ids)
    )
    return (
        grid.join(_counts(selected, "departures"), on=["station_id", "ts_utc"], how="left")
        .join(_counts(selected, "arrivals"), on=["station_id", "ts_utc"], how="left")
        .with_columns(
            pl.col("departures", "arrivals").fill_null(0),
            ts_local=pl.col("ts_utc").dt.convert_time_zone(LOCAL_TZ),
        )
        .select("station_id", "ts_utc", "ts_local", "departures", "arrivals")
        .sort("station_id", "ts_utc")
        .collect()
    )


def hourly_system_counts(clean: pl.LazyFrame, year: int) -> pl.DataFrame:
    """Network-wide departures per season hour (all stations, linked or not)."""
    counts = (
        clean.filter(pl.col("is_departure"))
        .group_by(pl.col("start_utc").dt.truncate(HOUR).alias("ts_utc"))
        .agg(pl.len().cast(pl.UInt32).alias("system_departures"))
    )
    return (
        season_hours(year)
        .lazy()
        .join(counts, on="ts_utc", how="left")
        .with_columns(
            pl.col("system_departures").fill_null(0),
            ts_local=pl.col("ts_utc").dt.convert_time_zone(LOCAL_TZ),
        )
        .select("ts_utc", "ts_local", "system_departures")
        .sort("ts_utc")
        .collect()
    )
