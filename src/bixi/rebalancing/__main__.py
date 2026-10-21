"""Run the rebalancing scenario analysis (Step 8).

Usage, from the project root (after: pip install -e ".[opt]"):
    python -m bixi.rebalancing            # all days in the forecast run, full scenario grid
    python -m bixi.rebalancing --quick    # three days, default scenario only

Inputs:  data/processed/forecasts/holdout-2025.parquet (Step 7 run file), reference stations
Outputs: data/processed/rebalancing/{results,summary,stops,inventory}.parquet, assumptions.json
         docs/rebalancing_results.md (generated; commit it)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import polars as pl

from bixi.config import get_settings
from bixi.rebalancing.model import Assumptions, build_day
from bixi.rebalancing.run import (
    STRATEGIES,
    inventory_frame,
    outcome_row,
    run_strategy,
    scenario_grid,
    stop_rows,
    travel_for,
)
from bixi.rebalancing.summary import summarize, write_report

DEFAULT = Assumptions()  # the scenario shown in detail: half-full stations, two trucks
REPORT = Path("docs/rebalancing_results.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BIXI rebalancing scenario analysis")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--run-file", type=Path, default=None)
    parser.add_argument("--time-limit", type=float, default=1.0, help="OR-Tools seconds per plan")
    args = parser.parse_args(argv)

    settings = get_settings()
    run_file = args.run_file or settings.processed_dir / "forecasts" / "holdout-2025.parquet"
    if not run_file.exists():
        print(f"Missing {run_file}. Run: python -m bixi.forecast export-holdout")
        return 1
    forecasts = pl.read_parquet(run_file)
    stations = pl.read_csv(
        settings.reference_dir / "selected_stations.csv", schema_overrides={"station_id": pl.String}
    )
    days = sorted(forecasts["local_date"].unique().to_list())
    scenarios = scenario_grid()
    if args.quick:
        days, scenarios = days[:3], [DEFAULT]

    rows, stops, inventories = [], [], []
    t0 = time.perf_counter()
    for i, day_date in enumerate(days, 1):
        day = build_day(forecasts, stations, day_date)
        travel = travel_for(day, DEFAULT)
        for a in scenarios:
            detail = a.start_fill == DEFAULT.start_fill and a.trucks == DEFAULT.trucks
            for strategy in STRATEGIES:
                outcome = run_strategy(day, a, strategy, travel, args.time_limit)
                rows.append(outcome_row(day, a, outcome))
                if detail:
                    stops.extend(stop_rows(day, outcome))
                    inventories.append(inventory_frame(day, outcome))
        print(f"{day_date} done ({i}/{len(days)}, {time.perf_counter() - t0:,.0f} s)", flush=True)

    out = settings.processed_dir / "rebalancing"
    out.mkdir(parents=True, exist_ok=True)
    results = pl.DataFrame(rows)
    summary = summarize(results)
    results.write_parquet(out / "results.parquet")
    summary.write_parquet(out / "summary.parquet")
    pl.DataFrame(stops).write_parquet(out / "stops.parquet")
    pl.concat(inventories).write_parquet(out / "inventory.parquet")
    (out / "assumptions.json").write_text(
        json.dumps({**asdict(DEFAULT), "run_file": run_file.name, "days": len(days)}, indent=2),
        encoding="utf-8",
    )
    print(write_report(summary, results, DEFAULT, len(days), REPORT))
    print(f"Done in {time.perf_counter() - t0:,.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
