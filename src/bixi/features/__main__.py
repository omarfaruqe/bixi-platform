"""Build data/processed/features.parquet (Step 5).

Usage, from the project root:
    python -m bixi.features
Needs: hourly tables from ``python -m bixi.ingest``, weather archive files, and (for the
production model) day-ahead forecasts from ``python -m bixi.download weather-forecast``.
"""

from __future__ import annotations

import sys

import polars as pl

from bixi.config import get_settings
from bixi.features.build import FEATURE_GROUPS, TARGETS, build_features
from bixi.features.events import load_events, station_event_features
from bixi.features.weather import forecast_weather, observed_weather


def main() -> int:
    settings = get_settings()
    processed, raw, reference = settings.processed_dir, settings.raw_dir, settings.reference_dir
    hourly_path = processed / "hourly_station.parquet"
    if not hourly_path.exists():
        print(f"Missing {hourly_path}. Run: python -m bixi.ingest")
        return 1

    archive = sorted((raw / "weather").glob("open_meteo_archive_*.json"))
    forecasts = sorted((raw / "weather").glob("open_meteo_previous_runs_*.json"))
    if not archive:
        print("Missing weather archive. Run: python -m bixi.download weather")
        return 1
    if not forecasts:
        print(
            "WARNING: no day-ahead forecasts; fc_* columns will be empty. "
            "Run: python -m bixi.download weather-forecast"
        )

    stations = pl.read_csv(
        reference / "selected_stations.csv", schema_overrides={"station_id": pl.String}
    )
    hourly = pl.read_parquet(hourly_path)
    df = build_features(
        hourly=hourly,
        stations=stations,
        system=pl.read_parquet(processed / "hourly_system.parquet"),
        observed=observed_weather(archive),
        forecast=forecast_weather(forecasts) if forecasts else None,
        events=station_event_features(load_events(reference / "events.csv"), stations),
    )
    out = processed / "features.parquet"
    df.write_parquet(out)

    lines = [
        "BIXI modelling table (features.parquet)",
        f"rows: {df.height:,} (hourly table: {hourly.height:,}); columns: {df.width}",
        f"targets: {', '.join(TARGETS)}",
        "",
        "--- Missing values by feature (share of rows) ---",
    ]
    for group, columns in FEATURE_GROUPS.items():
        lines.append(f"[{group}]")
        for column in columns:
            share = df[column].null_count() / df.height
            lines.append(f"  {column:<32} {share:6.1%}")

    if forecasts:
        both = df.select(
            "ts_utc",
            "obs_temperature_2m",
            "fc_temperature_2m",
            "obs_precipitation",
            "fc_precipitation",
            pl.col("local_date").dt.year().alias("year"),
        ).unique("ts_utc")
        quality = (
            both.drop_nulls(["fc_temperature_2m"])
            .group_by("year")
            .agg(
                pl.len().alias("hours"),
                (pl.col("fc_temperature_2m") - pl.col("obs_temperature_2m"))
                .abs()
                .mean()
                .alias("temp_mae_c"),
                ((pl.col("fc_precipitation") >= 0.2) == (pl.col("obs_precipitation") >= 0.2))
                .mean()
                .alias("rain_flag_agreement"),
            )
            .sort("year")
        )
        lines += ["", "--- Day-ahead forecast vs observed weather ---"]
        for r in quality.iter_rows(named=True):
            mae = "n/a" if r["temp_mae_c"] is None else f"{r['temp_mae_c']:.2f} C"
            rain = (
                "n/a (no precipitation forecast)"
                if r["rain_flag_agreement"] is None
                else f"{r['rain_flag_agreement']:.1%}"
            )
            lines.append(
                f"{r['year']}: {r['hours']:,} hours with forecasts; temperature MAE {mae}; "
                f"rain/no-rain agreement {rain}"
            )
        coverage = (
            both.group_by("year")
            .agg(
                pl.col("fc_temperature_2m").is_not_null().mean().alias("temperature"),
                pl.col("fc_precipitation").is_not_null().mean().alias("precipitation"),
            )
            .sort("year")
        )
        lines.append("forecast coverage by year (temperature / precipitation):")
        for year, temp, rain in coverage.iter_rows():
            lines.append(f"  {year}: {temp:.0%} / {rain:.0%}")

    events = df.filter(pl.col("event_any") == 1)
    lines += [
        "",
        f"--- Events --- station-hours on event days: {events.height:,} "
        f"({events['local_date'].n_unique()} days)",
    ]
    text = "\n".join(lines) + "\n"
    (processed / "features_report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
