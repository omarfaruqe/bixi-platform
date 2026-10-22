"""Headline numbers for the Overview page, computed from the pipeline outputs.

Streamlit-free (and free of LightGBM and OR-Tools), so it is tested directly and the server image
can import it. Every function returns None when its input is missing or incomplete, and the page
then leaves that number out instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from bixi.analysis.patterns import station_flows
from bixi.models.names import MAIN
from bixi.models.summary import Headline, headline
from bixi.rebalancing.summary import scenario

HOLDOUT = "holdout"
NO_WEATHER = "lgbm_poisson_no_weather"
OPTIMIZED = "optimized_forecast"
RULE = "rule_forecast"
DEFAULT_FILL = 0.5
DEFAULT_TRUCKS = 2


@dataclass(frozen=True)
class Volume:
    departures: int
    stations: int
    first_year: int
    last_year: int


@dataclass(frozen=True)
class Commute:
    """The station that gains the most bikes on weekday mornings (7-10 h)."""

    station_id: str
    name: str
    gain: float  # mean net bikes gained per weekday morning
    capacity: int


@dataclass(frozen=True)
class Rebalancing:
    days: int
    problem_hours_none: float
    problem_hours: float
    reduction: float
    rule_reduction: float | None
    share_of_oracle: float | None
    km_saving_vs_rule: float | None  # 1 - optimized km / rule km


def volume(hourly: pl.DataFrame | None) -> Volume | None:
    if hourly is None or hourly.is_empty():
        return None
    years = hourly["year"]
    return Volume(
        departures=int(hourly["departures"].sum()),
        stations=hourly["station_id"].n_unique(),
        first_year=int(years.min()),
        last_year=int(years.max()),
    )


def commute(hourly: pl.DataFrame | None, stations: pl.DataFrame | None) -> Commute | None:
    if hourly is None or stations is None:
        return None
    flows = station_flows(hourly.filter(pl.col("day_type") == "weekday"), "morning_peak")
    if flows.is_empty():
        return None
    top = flows.sort("net_flow", descending=True).row(0, named=True)
    info = stations.filter(pl.col("station_id") == top["station_id"])
    if top["net_flow"] <= 0 or info.is_empty():
        return None
    row = info.row(0, named=True)
    return Commute(
        station_id=top["station_id"],
        name=row["name"],
        gain=float(top["net_flow"]),
        capacity=int(row["capacity"]),
    )


def forecast(overall: pl.DataFrame | None, target: str = "departures") -> Headline | None:
    """Main model versus the baselines on the holdout (never used for training or tuning)."""
    return None if overall is None else headline(overall, HOLDOUT, target)


def weather_gain(overall: pl.DataFrame | None, target: str = "departures") -> float | None:
    """Relative MAE reduction from adding day-ahead weather forecasts to the main model."""
    if overall is None:
        return None
    rows = overall.filter((pl.col("split") == HOLDOUT) & (pl.col("target") == target))
    mae = dict(rows.select("model", "mae").iter_rows())
    if MAIN not in mae or not mae.get(NO_WEATHER):
        return None
    return 1 - mae[MAIN] / mae[NO_WEATHER]


def rebalancing(
    summary: pl.DataFrame | None, fill: float = DEFAULT_FILL, trucks: int = DEFAULT_TRUCKS
) -> Rebalancing | None:
    if summary is None:
        return None
    rows = {r["strategy"]: r for r in scenario(summary, fill, trucks).iter_rows(named=True)}
    if OPTIMIZED not in rows or "none" not in rows:
        return None
    opt, rule = rows[OPTIMIZED], rows.get(RULE)
    km_saving = None
    if rule is not None and rule["truck_km"]:
        km_saving = 1 - opt["truck_km"] / rule["truck_km"]
    return Rebalancing(
        days=int(opt["days"]),
        problem_hours_none=float(rows["none"]["problem_hours"]),
        problem_hours=float(opt["problem_hours"]),
        reduction=float(opt["reduction"]),
        rule_reduction=None if rule is None else float(rule["reduction"]),
        share_of_oracle=opt["share_of_oracle"],
        km_saving_vs_rule=km_saving,
    )
