"""Build forecast runs and move them between files and the database.

A run travels as two files: ``<name>.parquet`` (one row per station, target and hour) and
``<name>.json`` (run metadata). They are built where the data and models live (the Mac) and
loaded into PostgreSQL where the API runs (the server), so the server needs neither LightGBM nor
the large backtest outputs.

Two ways to build a run:

* ``holdout``: the main model's day-ahead forecasts for the holdout (2025-10-01 to 2025-11-15),
  from the backtest. That model was trained before the holdout began, so these are honest
  forecasts, shown next to what actually happened.
* ``model``: the final models applied to a feature table for dates **after** their training
  period (for example the 2026 season once its trips are published). Dates the models were
  trained on are refused, so a run can never quietly show in-sample predictions.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from bixi.forecast.store import Run
from bixi.ingest.rules import LOCAL_TZ
from bixi.models.names import INTERVAL, MAIN

COLUMNS = [
    "station_id",
    "target",
    "ts_utc",
    "local_date",
    "local_hour",
    "yhat",
    "lo",
    "hi",
    "actual",
]
HOLDOUT_TRAINED_THROUGH = date(2025, 9, 30)  # holdout cutoff 2025-10-01 (early stopping included)


def _with_local(df: pl.DataFrame) -> pl.DataFrame:
    local = pl.col("ts_utc").dt.convert_time_zone(LOCAL_TZ)
    return df.with_columns(
        local_date=local.dt.date(), local_hour=local.dt.hour().cast(pl.Int16)
    ).select(COLUMNS)


def holdout_run(
    predictions: pl.DataFrame, metrics: pl.DataFrame | None = None
) -> tuple[Run, pl.DataFrame]:
    rows = predictions.filter((pl.col("split") == "holdout") & (pl.col("model") == MAIN))
    if rows.is_empty():
        raise ValueError("no holdout predictions for the main model; run python -m bixi.models")
    df = _with_local(
        rows.select(
            "station_id",
            "target",
            "ts_utc",
            pl.col("yhat").cast(pl.Float64),
            pl.col("lo").cast(pl.Float64),
            pl.col("hi").cast(pl.Float64),
            pl.col("y").cast(pl.Float64).alias("actual"),
        )
    ).sort("station_id", "target", "ts_utc")
    details = {
        "interval": list(INTERVAL),
        "interval_method": "LightGBM quantiles + split conformal calibration",
        "issued": "day-ahead: every feature is known 24 h before the hour it forecasts",
    }
    if metrics is not None:
        held = metrics.filter((pl.col("split") == "holdout") & (pl.col("model") == MAIN))
        details["metrics"] = {
            r["target"]: {"mae": r["mae"], "rmse": r["rmse"], "coverage": r.get("coverage")}
            for r in held.iter_rows(named=True)
        }
    run = Run(
        run_id="holdout-2025",
        created_at=datetime.now(UTC),
        source="holdout",
        model_variant=MAIN,
        trained_through=HOLDOUT_TRAINED_THROUGH,
        start_date=df["local_date"].min(),
        end_date=df["local_date"].max(),
        details=details,
    )
    return run, df


def model_run(
    features: pl.DataFrame, models_dir: Path, start: date, end: date
) -> tuple[Run, pl.DataFrame]:
    """Apply the final models to feature rows with local dates in [start, end]."""
    from bixi.models.lgbm import FittedModel  # LightGBM only needed for this path

    manifest = json.loads((models_dir / "manifest.json").read_text(encoding="utf-8"))
    trained_through = date.fromisoformat(manifest["trained_through_local_date"])
    if start <= trained_through:
        raise ValueError(
            f"start {start} is inside the training period (models trained through "
            f"{trained_through}); forecasts must be out of sample"
        )
    window = features.filter(pl.col("local_date").is_between(start, end))
    if window.is_empty():
        raise ValueError(f"no feature rows between {start} and {end}")
    frames = []
    for target, margin in manifest["interval_conformal_margin"].items():
        mean = FittedModel.load(models_dir / f"{target}_mean.txt").predict(window)
        lo = FittedModel.load(models_dir / f"{target}_q10.txt").predict(window)
        hi = FittedModel.load(models_dir / f"{target}_q90.txt").predict(window)
        frames.append(
            window.select(
                "station_id",
                "ts_utc",
                pl.lit(target).alias("target"),
                pl.Series("yhat", mean),
                pl.Series("lo", (lo - margin).clip(0.0)),
                pl.Series("hi", hi.clip(lo) + margin),
                pl.col(target).cast(pl.Float64).alias("actual"),
            )
        )
    df = _with_local(pl.concat(frames)).sort("station_id", "target", "ts_utc")
    run = Run(
        run_id=f"model-{start.isoformat()}-{end.isoformat()}",
        created_at=datetime.now(UTC),
        source="model",
        model_variant=manifest["variant"],
        trained_through=trained_through,
        start_date=start,
        end_date=end,
        details={
            "interval": manifest["interval"],
            "conformal_margin": manifest["interval_conformal_margin"],
        },
    )
    return run, df


def write_run(run: Run, df: pl.DataFrame, path: Path) -> None:
    """``path`` is the .parquet file; the metadata goes next to it as .json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    meta = {
        k: (v.isoformat() if isinstance(v, date | datetime) else v) for k, v in asdict(run).items()
    }
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def read_run(path: Path) -> tuple[Run, pl.DataFrame]:
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    run = Run(
        run_id=meta["run_id"],
        created_at=datetime.fromisoformat(meta["created_at"]),
        source=meta["source"],
        model_variant=meta["model_variant"],
        trained_through=date.fromisoformat(meta["trained_through"])
        if meta["trained_through"]
        else None,
        start_date=date.fromisoformat(meta["start_date"]),
        end_date=date.fromisoformat(meta["end_date"]),
        details=meta["details"],
    )
    return run, pl.read_parquet(path).select(COLUMNS)


def station_rows(stations: pl.DataFrame) -> list[dict]:
    return stations.select(
        "station_id", "name", "borough", "lat", "lon", "capacity", "volume_tier", "station_type"
    ).to_dicts()


def forecast_rows(df: pl.DataFrame) -> list[dict]:
    """Rows ready for the database: Python datetimes in UTC, NaN-free floats."""
    return df.with_columns(pl.col("local_hour").cast(pl.Int16)).to_dicts()
