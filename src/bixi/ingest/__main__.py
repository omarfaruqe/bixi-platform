"""Run the ingestion pipeline.

Usage, from the project root (after: pip install -e ".[data]"):
    python -m bixi.ingest                  # all years
    python -m bixi.ingest --years 2025     # one year, for a quick check
    python -m bixi.ingest --skip-clean     # rebuild hourly tables from existing clean Parquet
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import polars as pl

from bixi.config import get_settings
from bixi.ingest.hourly import hourly_station_counts, hourly_system_counts
from bixi.ingest.rules import YEARS
from bixi.ingest.trips import clean_trips, read_crosswalk, scan_raw

SELECTED = Path("reference/selected_stations.csv")


def load_station_ids(path: Path = SELECTED) -> list[str]:
    with path.open(encoding="utf-8") as fh:
        return [row["station_id"] for row in csv.DictReader(fh)]


def trip_stats(clean: pl.LazyFrame) -> dict[str, int]:
    return (
        clean.select(
            trips=pl.len(),
            departures=pl.col("is_departure").sum(),
            arrivals=pl.col("is_arrival").sum(),
            departures_linked=(
                pl.col("is_departure") & pl.col("start_station_id").is_not_null()
            ).sum(),
        )
        .collect()
        .row(0, named=True)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--years", type=int, nargs="+", default=list(YEARS))
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="reuse data/processed/trips_clean/<year>.parquet instead of re-reading the CSVs",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    processed = settings.processed_dir
    crosswalk_path = processed / "station_crosswalk.csv"
    if not crosswalk_path.exists() or not SELECTED.exists():
        print("Missing station crosswalk or selection. Run: python scripts/select_stations.py")
        return 1
    crosswalk = read_crosswalk(crosswalk_path)
    station_ids = load_station_ids()

    trips_dir = processed / "trips_clean"
    trips_dir.mkdir(parents=True, exist_ok=True)
    report = ["BIXI ingestion report", ""]
    station_tables, system_tables = [], []

    for year in args.years:
        t0 = time.perf_counter()
        out = trips_dir / f"{year}.parquet"
        if args.skip_clean and out.exists():
            print(f"{year}: reusing {out}", flush=True)
        else:
            paths = sorted((settings.raw_dir / "trips" / str(year)).glob("*.csv"))
            if not paths:
                print(f"No raw CSV for {year} under {settings.raw_dir}/trips/{year}/")
                return 1
            print(f"{year}: cleaning {len(paths)} file(s)...", flush=True)
            clean_trips(scan_raw(paths), crosswalk).sink_parquet(out)
        clean = pl.scan_parquet(out)
        stats = trip_stats(clean)
        station_tables.append(hourly_station_counts(clean, station_ids, year))
        system_tables.append(hourly_system_counts(clean, year))
        seconds = time.perf_counter() - t0

        n = stats["trips"]
        report += [
            f"--- {year} ({seconds:,.0f} s) ---",
            f"trips: {n:,}",
            f"departures kept: {stats['departures']:,} ({stats['departures'] / n:.2%})",
            f"arrivals kept: {stats['arrivals']:,} ({stats['arrivals'] / n:.2%})",
            f"departures at a linked station: "
            f"{stats['departures_linked'] / max(stats['departures'], 1):.2%}",
            "",
        ]
        print(f"{year}: done in {seconds:,.0f} s", flush=True)

    stations = pl.concat(station_tables).sort("station_id", "ts_utc")
    system = pl.concat(system_tables).sort("ts_utc")
    stations.write_parquet(processed / "hourly_station.parquet")
    system.write_parquet(processed / "hourly_system.parquet")

    hours = system.height
    expected_rows = hours * len(station_ids)
    totals = stations.select(pl.col("departures", "arrivals").sum()).row(0, named=True)
    zero_share = stations.select(
        ((pl.col("departures") == 0) & (pl.col("arrivals") == 0)).mean()
    ).item()
    per_station = stations.group_by("station_id").agg(pl.col("departures").sum()).sort("departures")
    report += [
        "--- hourly_station.parquet ---",
        f"stations: {stations['station_id'].n_unique()} (expected {len(station_ids)})",
        f"rows: {stations.height:,} (expected {expected_rows:,} = {len(station_ids)} x {hours:,})",
        f"season departures: {totals['departures']:,}; arrivals: {totals['arrivals']:,}",
        f"station-hours with no departure and no arrival: {zero_share:.1%}",
        f"departures per station, season total: min {per_station['departures'].min():,}, "
        f"median {int(per_station['departures'].median()):,}, "
        f"max {per_station['departures'].max():,}",
        "",
        "--- hourly_system.parquet ---",
        f"hours: {hours:,}; peak hour departures: {system['system_departures'].max():,}",
    ]
    if stations.height != expected_rows:
        report.append("WARNING: row count differs from the full grid")

    text = "\n".join(report) + "\n"
    (processed / "ingest_report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
