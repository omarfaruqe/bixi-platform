"""Rolling-origin backtests and the final holdout (docs/decisions.md, section 3).

Folds (local dates, 2025 season):
    cutoff 2025-06-01 -> test June       cutoff 2025-08-01 -> test August
    cutoff 2025-07-01 -> test July       cutoff 2025-09-01 -> test September
    HOLDOUT: cutoff 2025-10-01 -> test 2025-10-01 ... 2025-11-15, looked at once, at the end.

For each fold a model trains on its window up to ``cutoff - 14 days`` and early-stops on the last
14 days before the cutoff. Quantile models (80% intervals) are fitted for the holdout only, then
calibrated with split conformal prediction on those same 14 days.
Nothing at or after the cutoff is used to fit anything, baselines included. Inside a test window,
features stay 24 h-safe (Step 5), which simulates a forecast re-issued every day.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import polars as pl
from scipy.stats import poisson

from bixi.features.build import FEATURE_GROUPS, TARGETS, production_features
from bixi.models import lgbm
from bixi.models.baselines import BASELINES, predict_baseline
from bixi.models.metrics import conformal_margin, summarize
from bixi.models.names import INTERVAL, MAIN

VALID_DAYS = 14


@dataclass(frozen=True)
class Fold:
    name: str
    cutoff: date
    end: date  # exclusive
    split: str  # "backtest" or "holdout"


FOLDS = (
    Fold("2025-06", date(2025, 6, 1), date(2025, 7, 1), "backtest"),
    Fold("2025-07", date(2025, 7, 1), date(2025, 8, 1), "backtest"),
    Fold("2025-08", date(2025, 8, 1), date(2025, 9, 1), "backtest"),
    Fold("2025-09", date(2025, 9, 1), date(2025, 10, 1), "backtest"),
    Fold("holdout", date(2025, 10, 1), date(2025, 11, 16), "holdout"),
)


def _without(features: list[str], group: str) -> list[str]:
    drop = set(FEATURE_GROUPS[group])
    return [f for f in features if f not in drop]


@dataclass(frozen=True)
class Variant:
    name: str
    objective: str
    features: list[str]
    first_year: int
    purpose: str


def variants() -> list[Variant]:
    prod = production_features()
    no_weather = _without(prod, "weather_forecast")
    return [
        Variant(MAIN, "poisson", prod, 2024, "main model"),
        Variant("lgbm_l2", "l2", prod, 2024, "objective comparison"),
        Variant("lgbm_tweedie", "tweedie", prod, 2024, "objective comparison"),
        Variant(
            "lgbm_poisson_all_years",
            "poisson",
            prod,
            2023,
            "adds 2023 (temperature-only forecasts)",
        ),
        Variant(
            "lgbm_poisson_no_weather", "poisson", no_weather, 2024, "value of weather forecasts"
        ),
        Variant(
            "lgbm_poisson_oracle",
            "poisson",
            no_weather + FEATURE_GROUPS["weather_observed"],
            2024,
            "observed weather: upper bound, not deployable",
        ),
    ]


def split(
    df: pl.DataFrame, fold: Fold, first_year: int
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    window = df.filter(pl.col("year") >= first_year)
    valid_start = fold.cutoff - timedelta(days=VALID_DAYS)
    train = window.filter(pl.col("local_date") < valid_start)
    valid = window.filter(pl.col("local_date").is_between(valid_start, fold.cutoff, closed="left"))
    test = df.filter(pl.col("local_date").is_between(fold.cutoff, fold.end, closed="left"))
    return train, valid, test


def _frame(
    test: pl.DataFrame, fold: Fold, model: str, target: str, yhat, lo=None, hi=None
) -> pl.DataFrame:
    out = test.select(
        "station_id",
        "ts_utc",
        "local_date",
        "local_hour",
        "day_type",
        "event_any",
        "obs_is_rainy",
        "volume_tier",
        "station_type",
        pl.col(target).cast(pl.Float64).alias("y"),
    ).with_columns(
        pl.Series("yhat", np.asarray(yhat, dtype=float)),
        pl.lit(fold.name).alias("fold"),
        pl.lit(fold.split).alias("split"),
        pl.lit(model).alias("model"),
        pl.lit(target).alias("target"),
    )
    if lo is not None:
        out = out.with_columns(
            pl.Series("lo", np.asarray(lo, dtype=float)),
            pl.Series("hi", np.asarray(hi, dtype=float)),
        )
    else:
        out = out.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("lo"), pl.lit(None, dtype=pl.Float64).alias("hi")
        )
    return out


def run(
    df: pl.DataFrame,
    folds: Iterable[Fold] = FOLDS,
    variant_list: list[Variant] | None = None,
    targets: Iterable[str] = TARGETS,
    log: Callable[[str], None] = print,
    max_rounds: int = lgbm.MAX_ROUNDS,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, int]]:
    """Return (predictions, feature importance of the main holdout model, best iterations)."""
    variant_list = variant_list if variant_list is not None else variants()
    encoding = lgbm.Encoding.fit(df)
    predictions: list[pl.DataFrame] = []
    importance: list[pl.DataFrame] = []
    best_rounds: dict[str, int] = {}
    for fold in folds:
        for target in targets:
            train24, _, test = split(df, fold, 2024)
            for name in BASELINES:
                yhat = predict_baseline(name, train24, test, target)
                predictions.append(_frame(test, fold, name, target, yhat))
            for v in variant_list:
                train, valid, test = split(df, fold, v.first_year)
                model = lgbm.fit(
                    train,
                    valid,
                    target,
                    v.features,
                    v.objective,
                    encoding=encoding,
                    max_rounds=max_rounds,
                )
                yhat = model.predict(test)
                lo = hi = None
                if v.name == MAIN and fold.split == "holdout":
                    q_lo = lgbm.fit(
                        train,
                        valid,
                        target,
                        v.features,
                        "quantile",
                        INTERVAL[0],
                        encoding,
                        max_rounds,
                    )
                    q_hi = lgbm.fit(
                        train,
                        valid,
                        target,
                        v.features,
                        "quantile",
                        INTERVAL[1],
                        encoding,
                        max_rounds,
                    )
                    raw_lo, raw_hi = q_lo.predict(test), q_hi.predict(test)
                    raw_hi = np.maximum(raw_hi, raw_lo)
                    # Conformal calibration on the 14 validation days just before the cutoff.
                    margin = conformal_margin(
                        valid[target].cast(pl.Float64).to_numpy(),
                        q_lo.predict(valid),
                        q_hi.predict(valid),
                        INTERVAL[1] - INTERVAL[0],
                    )
                    lo = np.maximum(raw_lo - margin, 0.0)
                    hi = raw_hi + margin
                    predictions.append(
                        _frame(test, fold, "quantile_raw_interval", target, yhat, raw_lo, raw_hi)
                    )
                    log(f"{fold.name} {target:<10} conformal margin {margin:+.3f}")
                    # Reference: the interval a pure Poisson assumption would give.
                    predictions.append(
                        _frame(
                            test,
                            fold,
                            "poisson_assumption_interval",
                            target,
                            yhat,
                            poisson.ppf(INTERVAL[0], np.maximum(yhat, 1e-9)),
                            poisson.ppf(INTERVAL[1], np.maximum(yhat, 1e-9)),
                        )
                    )
                    if fold.split == "holdout":
                        importance.append(
                            model.importance().with_columns(pl.lit(target).alias("target"))
                        )
                        best_rounds[target] = model.best_iteration
                predictions.append(_frame(test, fold, v.name, target, yhat, lo, hi))
                log(f"{fold.name} {target:<10} {v.name:<26} rounds={model.best_iteration}")
    return (
        pl.concat(predictions),
        pl.concat(importance) if importance else pl.DataFrame(),
        best_rounds,
    )


def metric_tables(pred: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Every summary the report and the dashboard need."""
    main_like = pred.filter(
        pl.col("model").is_in([MAIN, "seasonal_naive", "same_hour_4w", "profile_mean"])
    )
    holdout = main_like.filter(pl.col("split") == "holdout")
    return {
        "metrics_by_fold": summarize(pred, ["split", "fold", "target", "model"]),
        "metrics_overall": summarize(pred, ["split", "target", "model"]),
        "errors_by_hour": summarize(holdout, ["target", "model", "local_hour"]),
        "errors_by_station": summarize(
            holdout, ["target", "model", "station_id", "volume_tier", "station_type"]
        ),
        "errors_by_condition": pl.concat(
            [
                summarize(
                    holdout.with_columns(pl.col(c).cast(pl.String).alias("value")),
                    ["target", "model", "value"],
                ).with_columns(pl.lit(c).alias("condition"))
                for c in ("day_type", "obs_is_rainy", "event_any")
            ]
        ),
    }
