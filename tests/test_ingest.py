"""Ingestion tests on a tiny synthetic trip file (no real data needed)."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from bixi.ingest.hourly import hourly_station_counts, hourly_system_counts, season_hours
from bixi.ingest.rules import RAW_COLUMNS, season_bounds_utc
from bixi.ingest.trips import clean_trips, read_crosswalk, scan_raw

HEADER = list(RAW_COLUMNS)


def ms(*args: int) -> int:
    return int(datetime(*args, tzinfo=UTC).timestamp() * 1000)


T0 = ms(2025, 7, 1, 12, 10)  # 08:10 in Montréal (UTC-4)


def trip(start: str | None, end: str | None, start_ms: int, end_ms: int | None) -> list:
    return [start, "Ville-Marie", 45.5, -73.57, end, "Ville-Marie", 45.51, -73.56, start_ms, end_ms]


# Polars joins do not keep row order, so tests sort by trip duration (all distinct below).
TRIPS = [
    trip("A", "B", T0, T0 + 600_000),  # normal: departure A at 12h, arrival B at 12h
    trip("A", "A", T0, T0 + 30_000),  # same-station 30 s: false start, dropped
    trip("A", "A", T0, T0 + 900_000),  # same-station 15 min: a real round trip
    trip("B", None, T0, None),  # no end: departure only
    trip("B", "A", T0, T0 + 25 * 3600 * 1000),  # over 24 h: departure only
    trip("Old A name", "Unlinked", T0 + 3_600_000, T0 + 3_960_000),  # renamed + unlinked names
]


@pytest.fixture
def clean(tmp_path) -> pl.LazyFrame:
    raw = tmp_path / "trips.csv"
    pl.DataFrame(TRIPS, schema=HEADER, orient="row").write_csv(raw)
    crosswalk = tmp_path / "crosswalk.csv"
    crosswalk.write_text(
        "historical_name,station_id,live_name,distance_m\n"
        "A,1,A,0.0\nOld A name,1,A,12.0\nB,2,B,0.0\nUnlinked,,,300.0\n",
        encoding="utf-8",
    )
    return clean_trips(scan_raw([raw]), read_crosswalk(crosswalk))


def ordered(clean: pl.LazyFrame) -> pl.DataFrame:
    """Rows back in TRIPS order, keyed by their distinct durations."""
    order = {600.0: 0, 30.0: 1, 900.0: 2, None: 3, 90_000.0: 4, 360.0: 5}
    df = clean.collect()
    return df.with_columns(
        pl.col("duration_s").replace_strict(order, return_dtype=pl.Int8).alias("_i")
    ).sort("_i")


def test_rules_flag_departures_and_arrivals(clean):
    df = ordered(clean)
    assert df["is_departure"].to_list() == [True, False, True, True, True, True]
    assert df["is_arrival"].to_list() == [True, False, True, False, False, True]


def test_crosswalk_attaches_ids_and_merges_renames(clean):
    df = ordered(clean)
    assert df["start_station_id"].to_list() == ["1", "1", "1", "2", "2", "1"]
    assert df["end_station_id"].to_list()[-1] is None
    assert df["start_utc"].dtype == pl.Datetime("ms", "UTC")


def test_season_grid_keeps_the_repeated_fall_back_hour():
    hours = season_hours(2025)
    start, end = season_bounds_utc(2025)
    days = (end.date() - start.date()).days  # 214 days, April 15 to November 15
    assert hours.height == days * 24 + 1  # DST ends November 2: one extra hour
    assert hours["ts_utc"].is_unique().all()


def test_hourly_station_counts_fill_zeros_on_full_grid(clean):
    table = hourly_station_counts(clean, ["1", "2"], 2025)
    assert table.height == 2 * season_hours(2025).height
    noon = table.filter(pl.col("ts_utc") == datetime(2025, 7, 1, 12, tzinfo=UTC))
    by_station = {r["station_id"]: r for r in noon.iter_rows(named=True)}
    assert by_station["1"]["departures"] == 2  # normal trip + round trip, not the false start
    assert by_station["1"]["arrivals"] == 1  # the round trip; the false start is not counted
    assert by_station["2"]["departures"] == 2
    assert by_station["2"]["arrivals"] == 1
    assert by_station["1"]["ts_local"].hour == 8
    assert table["departures"].sum() == 5


def test_hourly_system_counts(clean):
    table = hourly_system_counts(clean, 2025)
    assert table["system_departures"].sum() == 5
