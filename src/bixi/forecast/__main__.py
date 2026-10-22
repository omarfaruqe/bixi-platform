"""Forecast runs: export to files, publish to the database, switch the active run.

On the Mac (where the data and models are):
    python -m bixi.forecast export-holdout
        -> data/processed/forecasts/holdout-2025.parquet (+ .json)
    python -m bixi.forecast export-model --start 2026-05-01 --end 2026-05-31
        -> forecasts from the final models for dates after their training period

Wherever the database is (DATABASE_URL), e.g. in the API container on the server:
    python -m bixi.forecast publish data/processed/forecasts/holdout-2025.parquet
    python -m bixi.forecast runs
    python -m bixi.forecast activate holdout-2025
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import polars as pl

from bixi.config import get_settings
from bixi.forecast import publish, store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bixi.forecast", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("export-holdout", help="holdout forecasts from the Step 6 backtest")
    model = sub.add_parser("export-model", help="final models on dates after training")
    model.add_argument("--start", type=date.fromisoformat, required=True)
    model.add_argument("--end", type=date.fromisoformat, required=True)
    pub = sub.add_parser("publish", help="load a run file into the database and activate it")
    pub.add_argument("path", type=Path)
    pub.add_argument("--no-activate", action="store_true")
    sub.add_parser("runs", help="list runs in the database")
    act = sub.add_parser("activate", help="make a published run the one the API serves")
    act.add_argument("run_id")
    args = parser.parse_args(argv)

    settings = get_settings()
    out_dir = settings.processed_dir / "forecasts"

    if args.command == "export-holdout":
        results = settings.processed_dir / "model_results"
        predictions = pl.read_parquet(results / "predictions.parquet")
        metrics_path = results / "metrics_overall.parquet"
        metrics = pl.read_parquet(metrics_path) if metrics_path.exists() else None
        run, df = publish.holdout_run(predictions, metrics)
        path = out_dir / f"{run.run_id}.parquet"
        publish.write_run(run, df, path)
        print(f"Wrote {path} ({df.height:,} rows, {run.start_date} to {run.end_date})")
        return 0

    if args.command == "export-model":
        features = pl.read_parquet(settings.processed_dir / "features.parquet")
        run, df = publish.model_run(features, settings.data_dir / "models", args.start, args.end)
        path = out_dir / f"{run.run_id}.parquet"
        publish.write_run(run, df, path)
        print(f"Wrote {path} ({df.height:,} rows)")
        return 0

    engine = store.engine_for(settings.database_url)
    store.create_schema(engine)

    if args.command == "publish":
        run, df = publish.read_run(args.path)
        stations = pl.read_csv(
            settings.reference_dir / "selected_stations.csv",
            schema_overrides={"station_id": pl.String},
        )
        store.upsert_stations(engine, publish.station_rows(stations))
        count = store.publish_run(
            engine, run, publish.forecast_rows(df), activate=not args.no_activate
        )
        state = "and activated" if not args.no_activate else "(not activated)"
        print(f"Published run {run.run_id}: {count:,} forecasts {state}")
        return 0

    if args.command == "runs":
        for r in store.list_runs(engine):
            flag = "*" if r["is_active"] else " "
            print(f"{flag} {r['run_id']:<32} {r['source']:<8} {r['start_date']} .. {r['end_date']}")
        return 0

    if args.command == "activate":
        try:
            store.activate(engine, args.run_id)
        except KeyError:
            known = ", ".join(r["run_id"] for r in store.list_runs(engine)) or "none"
            print(f"Unknown run {args.run_id!r}. Published runs: {known}", file=sys.stderr)
            return 1
        print(f"Active run: {args.run_id}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
