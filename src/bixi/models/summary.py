"""Summaries of the backtest tables for the dashboard and the report. Streamlit-free."""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from bixi.features.build import FEATURE_GROUPS
from bixi.models.baselines import BASELINES
from bixi.models.metrics import skill
from bixi.models.names import MAIN

COMPARISON_MODELS = (
    MAIN,
    "lgbm_l2",
    "lgbm_tweedie",
    "lgbm_poisson_all_years",
    "lgbm_poisson_no_weather",
    *BASELINES,
)
INGREDIENTS = (
    "lgbm_poisson_no_weather",
    MAIN,
    "lgbm_poisson_oracle",
    "lgbm_poisson_all_years",
)


@dataclass(frozen=True)
class Headline:
    mae: float
    skill_vs_naive: float
    skill_vs_best_baseline: float
    best_baseline: str
    coverage: float | None


def _rows(overall: pl.DataFrame, split: str, target: str) -> pl.DataFrame:
    return overall.filter((pl.col("split") == split) & (pl.col("target") == target))


def headline(overall: pl.DataFrame, split: str, target: str) -> Headline | None:
    rows = _rows(overall, split, target)
    mae = dict(rows.select("model", "mae").iter_rows())
    if MAIN not in mae or "seasonal_naive" not in mae:
        return None
    baselines = {b: mae[b] for b in BASELINES if b in mae}
    best = min(baselines, key=baselines.get)
    main_row = rows.filter(pl.col("model") == MAIN).row(0, named=True)
    return Headline(
        mae=mae[MAIN],
        skill_vs_naive=skill(mae[MAIN], mae["seasonal_naive"]),
        skill_vs_best_baseline=skill(mae[MAIN], baselines[best]),
        best_baseline=best,
        coverage=main_row.get("coverage"),
    )


def comparison(overall: pl.DataFrame, split: str, target: str) -> pl.DataFrame:
    """Deployable models and baselines (no oracle, no interval reference)."""
    return _rows(overall, split, target).filter(pl.col("model").is_in(COMPARISON_MODELS))


def ingredients(overall: pl.DataFrame, split: str, target: str) -> pl.DataFrame:
    """What weather and extra years add: MAE and skill versus the main model's naive baseline."""
    rows = _rows(overall, split, target)
    naive = rows.filter(pl.col("model") == "seasonal_naive")["mae"]
    naive_mae = naive[0] if naive.len() else None
    order = {m: i for i, m in enumerate(INGREDIENTS)}
    return (
        rows.filter(pl.col("model").is_in(INGREDIENTS))
        .with_columns(
            skill=pl.lit(1.0) - pl.col("mae") / naive_mae if naive_mae else pl.lit(None),
            _o=pl.col("model").replace_strict(order, return_dtype=pl.Int8),
        )
        .sort("_o")
        .drop("_o")
    )


def importance_by_group(importance: pl.DataFrame, target: str) -> pl.DataFrame:
    lookup = {f: g for g, fs in FEATURE_GROUPS.items() for f in fs}
    return (
        importance.filter(pl.col("target") == target)
        .with_columns(group=pl.col("feature").replace_strict(lookup, default="other"))
        .group_by("group")
        .agg(pl.col("gain_share").sum())
        .sort("gain_share", descending=True)
    )


def hardest_stations(by_station: pl.DataFrame, target: str, n: int = 8) -> pl.DataFrame:
    """Main-model stations with the largest error relative to their volume."""
    return (
        by_station.filter((pl.col("target") == target) & (pl.col("model") == MAIN))
        .with_columns(relative_error=pl.col("mae") / pl.col("mean_actual"))
        .sort("relative_error", descending=True)
        .head(n)
    )
