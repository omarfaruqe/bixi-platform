"""Baselines every model must beat. All use only information available a day ahead.

* ``seasonal_naive``: the same hour one week earlier (``<target>_lag_168``).
* ``same_hour_4w``: the mean of the same hour over the previous four weeks.
* ``profile_mean``: the training-period mean for the station, local hour and day type.
"""

from __future__ import annotations

import polars as pl

BASELINES = ("seasonal_naive", "same_hour_4w", "profile_mean")


def seasonal_naive(test: pl.DataFrame, target: str) -> pl.Series:
    return (
        test[f"{target}_lag_168"]
        .fill_null(test[f"{target}_lag_24"])
        .fill_null(0.0)
        .cast(pl.Float64)
    )


def same_hour_4w(test: pl.DataFrame, target: str) -> pl.Series:
    return (
        test[f"{target}_same_hour_4w"]
        .fill_null(test[f"{target}_lag_24"])
        .fill_null(0.0)
        .cast(pl.Float64)
    )


def profile_mean(train: pl.DataFrame, test: pl.DataFrame, target: str) -> pl.Series:
    keys = ["station_id", "local_hour", "day_type"]
    profile = train.group_by(keys).agg(pl.col(target).cast(pl.Float64).mean().alias("_p"))
    station_hour = train.group_by(["station_id", "local_hour"]).agg(
        pl.col(target).cast(pl.Float64).mean().alias("_sh")
    )
    out = (
        test.select(keys)
        .with_row_index("_i")
        .join(profile, on=keys, how="left")
        .join(station_hour, on=["station_id", "local_hour"], how="left")
        .sort("_i")
    )
    # A day type unseen in training (e.g. a holiday) falls back to the station-hour mean.
    return out["_p"].fill_null(out["_sh"]).fill_null(0.0)


def predict_baseline(name: str, train: pl.DataFrame, test: pl.DataFrame, target: str) -> pl.Series:
    if name == "seasonal_naive":
        return seasonal_naive(test, target)
    if name == "same_hour_4w":
        return same_hour_4w(test, target)
    if name == "profile_mean":
        return profile_mean(train, test, target)
    raise ValueError(f"unknown baseline {name!r}")
