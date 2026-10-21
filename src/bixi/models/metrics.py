"""Forecast metrics for hourly counts (docs/decisions.md, section 3).

* MAE and RMSE: errors in trips per station-hour.
* Mean Poisson deviance: the natural loss for counts; it judges the predicted *rate*, so it does
  not reward a model for hugging zero during quiet hours.
* Interval coverage and width: for 80% intervals, coverage should be close to 0.80.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import polars as pl

EPS = 1e-9


def poisson_deviance_expr(y: str = "y", yhat: str = "yhat") -> pl.Expr:
    """Per-row Poisson deviance: 2 * (y log(y / mu) - (y - mu)), with mu clipped above zero."""
    mu = pl.col(yhat).clip(lower_bound=EPS)
    y_ = pl.col(y)
    term = pl.when(y_ > 0).then(y_ * (y_ / mu).log()).otherwise(0.0)
    return 2 * (term - (y_ - mu))


def summarize(df: pl.DataFrame, by: Sequence[str] = ()) -> pl.DataFrame:
    """Metrics per group. Expects columns y, yhat and optionally lo, hi (interval bounds)."""
    error = pl.col("yhat") - pl.col("y")
    aggs = [
        pl.len().alias("n"),
        error.abs().mean().alias("mae"),
        (error**2).mean().sqrt().alias("rmse"),
        poisson_deviance_expr().mean().alias("poisson_deviance"),
        pl.col("y").mean().alias("mean_actual"),
        pl.col("yhat").mean().alias("mean_forecast"),
    ]
    if {"lo", "hi"} <= set(df.columns):
        aggs += [
            ((pl.col("y") >= pl.col("lo")) & (pl.col("y") <= pl.col("hi")))
            .mean()
            .alias("coverage"),
            (pl.col("hi") - pl.col("lo")).mean().alias("interval_width"),
        ]
    if by:
        return df.group_by(list(by)).agg(aggs).sort(list(by))
    return df.select(aggs)


def skill(model_mae: float, baseline_mae: float) -> float:
    """Relative MAE improvement over a baseline: 0.25 means 25% lower error."""
    return 1.0 - model_mae / baseline_mae if baseline_mae else 0.0


def conformal_margin(y, lo, hi, coverage: float) -> float:
    """Split-conformal margin for an interval (conformalized quantile regression).

    Score = how far each actual falls outside [lo, hi] (negative when inside). Widening the
    interval by the adjusted ``coverage`` quantile of the scores, measured on held-out recent
    data, gives intervals that contain about ``coverage`` of new values. A negative margin
    narrows intervals that were too wide.
    """
    y, lo, hi = (np.asarray(a, dtype=float) for a in (y, lo, hi))
    scores = np.maximum(lo - y, y - hi)
    n = scores.size
    if n == 0:
        return 0.0
    level = min(1.0, math.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method="higher"))
