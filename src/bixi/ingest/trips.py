"""Read and clean raw trip CSVs with Polars (lazy, so a 2.8 GB file never sits in memory)."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from bixi.ingest.rules import FALSE_START_MAX_S, MAX_TRIP_S, RAW_COLUMNS

RAW_SCHEMA = {
    "STARTSTATIONNAME": pl.String,
    "STARTSTATIONARRONDISSEMENT": pl.String,
    "STARTSTATIONLATITUDE": pl.Float64,
    "STARTSTATIONLONGITUDE": pl.Float64,
    "ENDSTATIONNAME": pl.String,
    "ENDSTATIONARRONDISSEMENT": pl.String,
    "ENDSTATIONLATITUDE": pl.Float64,
    "ENDSTATIONLONGITUDE": pl.Float64,
    "STARTTIMEMS": pl.Int64,
    "ENDTIMEMS": pl.Int64,
}

CLEAN_COLUMNS = [
    "start_station_id",
    "end_station_id",
    "start_name",
    "end_name",
    "start_utc",
    "end_utc",
    "duration_s",
    "is_departure",
    "is_arrival",
]


UTC_MS = pl.Datetime("ms", "UTC")


def _utc(column: str) -> pl.Expr:
    """Epoch milliseconds -> timezone-aware UTC datetime with millisecond precision."""
    return pl.from_epoch(column, time_unit="ms").dt.replace_time_zone("UTC").cast(UTC_MS)


def scan_raw(paths: list[Path]) -> pl.LazyFrame:
    """Lazy scan of one or more raw trip CSVs, renamed to snake_case."""
    return pl.scan_csv(
        [str(p) for p in paths], schema=RAW_SCHEMA, has_header=True, encoding="utf8"
    ).rename(RAW_COLUMNS)


def read_crosswalk(path: Path) -> pl.LazyFrame:
    """historical_name -> station_id; names that did not link keep a null id."""
    return (
        pl.scan_csv(path, schema_overrides={"station_id": pl.String})
        .select(
            pl.col("historical_name"),
            pl.when(pl.col("station_id").str.len_chars() > 0).then(pl.col("station_id")),
        )
        .unique("historical_name")
    )


def clean_trips(raw: pl.LazyFrame, crosswalk: pl.LazyFrame) -> pl.LazyFrame:
    """Apply the section 8 rules and attach station ids.

    Coordinates are not carried forward: station locations come from the live GBFS feed, which
    also removes the need to handle the 0.0 / -1.0 coordinate sentinels row by row.
    """
    start_ids = crosswalk.rename(
        {"historical_name": "start_name", "station_id": "start_station_id"}
    )
    end_ids = crosswalk.rename({"historical_name": "end_name", "station_id": "end_station_id"})

    duration = (pl.col("end_ms") - pl.col("start_ms")) / 1000.0
    false_start = (pl.col("start_name") == pl.col("end_name")).fill_null(False) & (
        pl.col("duration_s") < FALSE_START_MAX_S
    ).fill_null(False)
    return (
        raw.filter(pl.col("start_ms").is_not_null())
        .with_columns(
            duration_s=duration,
            start_utc=_utc("start_ms"),
            end_utc=_utc("end_ms"),
        )
        .with_columns(
            is_departure=pl.col("start_name").is_not_null() & ~false_start,
            is_arrival=(
                pl.col("end_ms").is_not_null()
                & pl.col("end_name").is_not_null()
                & pl.col("duration_s").is_between(0, MAX_TRIP_S)
                & ~false_start
            ).fill_null(False),
        )
        .join(start_ids, on="start_name", how="left")
        .join(end_ids, on="end_name", how="left")
        .select(CLEAN_COLUMNS)
    )
