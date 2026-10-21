"""Run strategies over days and scenarios.

For each window: simulate the actual day up to the window start (earlier moves included), project
the inventory to the window end with the planning flows, compute targets for the hours until the
next window, plan the truck moves, and apply them at the window end. The finished day is always
scored with the **actual** flows.

Strategies:
    none                no rebalancing
    rule_forecast       rule of thumb, planned from day-ahead forecasts
    optimized_forecast  OR-Tools routing, planned from day-ahead forecasts (the method)
    optimized_oracle    OR-Tools routing with perfect knowledge of the day (upper bound)
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import polars as pl

from bixi.rebalancing.model import (
    Assumptions,
    Day,
    hour_positions,
    simulate,
    targets,
    travel_minutes,
)
from bixi.rebalancing.planning import Plan, optimized_plan, rule_plan

STRATEGIES = ("none", "rule_forecast", "optimized_forecast", "optimized_oracle")


@dataclass
class DayOutcome:
    strategy: str
    empty_hours: int
    full_hours: int
    missing_bikes: float
    missing_docks: float
    bikes_moved: int
    truck_km: float
    unmet_target_bikes: int  # imbalance the plan wanted to fix but could not reach in time
    plans: list[tuple[tuple[int, int], Plan]]
    inventory: np.ndarray


def run_strategy(
    day: Day, a: Assumptions, strategy: str, travel: np.ndarray, time_limit_s: float = 1.0
) -> DayOutcome:
    start = np.round(a.start_fill * day.capacity)
    net_actual = day.net_actual
    planning_net = net_actual if strategy == "optimized_oracle" else day.net_fc
    adjustments: dict[int, np.ndarray] = {}
    plans: list[tuple[tuple[int, int], Plan]] = []
    unmet = 0
    if strategy != "none":
        for k, window in enumerate(a.windows):
            p_start = hour_positions(day, window[0])
            p_end = hour_positions(day, window[1])
            last = k + 1 == len(a.windows)
            p_next = len(day.hours) if last else hour_positions(day, a.windows[k + 1][1])
            state = simulate(day, start, net_actual, adjustments).inventory[:, p_start]
            projected = np.clip(
                state + planning_net[:, p_start:p_end].sum(axis=1), 0.0, day.capacity
            )
            target = targets(projected, planning_net[:, p_end:p_next], day.capacity)
            diff = target - projected
            surplus = np.round(np.clip(-diff, 0, None)).astype(int)
            deficit = np.round(np.clip(diff, 0, None)).astype(int)
            if strategy == "rule_forecast":
                plan = rule_plan(surplus, deficit, travel, a, a.window_minutes(window))
            else:
                plan = optimized_plan(
                    surplus, deficit, travel, a, a.window_minutes(window), time_limit_s
                )
            delta = plan.net(len(day.station_ids))
            adjustments[p_end] = adjustments.get(p_end, 0.0) + delta
            reachable = min(surplus.sum(), deficit.sum())
            unmet += int(max(reachable - plan.bikes_moved, 0))
            plans.append((window, plan))
    result = simulate(day, start, net_actual, adjustments)
    return DayOutcome(
        strategy=strategy,
        empty_hours=result.empty_hours,
        full_hours=result.full_hours,
        missing_bikes=result.missing_bikes,
        missing_docks=result.missing_docks,
        bikes_moved=sum(p.bikes_moved for _, p in plans),
        truck_km=sum(p.km(a) for _, p in plans),
        unmet_target_bikes=unmet,
        plans=plans,
        inventory=result.inventory,
    )


def scenario_grid(
    fills: tuple[float, ...] = (0.3, 0.5, 0.7), trucks: tuple[int, ...] = (1, 2, 4)
) -> list[Assumptions]:
    base = Assumptions()
    return [replace(base, start_fill=f, trucks=k) for f in fills for k in trucks]


def outcome_row(day: Day, a: Assumptions, o: DayOutcome) -> dict:
    return {
        "date": day.date,
        "start_fill": a.start_fill,
        "trucks": a.trucks,
        "strategy": o.strategy,
        "empty_hours": o.empty_hours,
        "full_hours": o.full_hours,
        "problem_hours": o.empty_hours + o.full_hours,
        "missing_bikes": o.missing_bikes,
        "missing_docks": o.missing_docks,
        "bikes_moved": o.bikes_moved,
        "truck_km": o.truck_km,
        "unmet_target_bikes": o.unmet_target_bikes,
    }


def stop_rows(day: Day, o: DayOutcome) -> list[dict]:
    rows = []
    for window, plan in o.plans:
        for s in plan.stops:
            rows.append(
                {
                    "date": day.date,
                    "strategy": o.strategy,
                    "window_start": window[0],
                    "truck": s.truck,
                    "seq": s.seq,
                    "station_id": day.station_ids[s.station],
                    "bikes": s.bikes,
                }
            )
    return rows


def inventory_frame(day: Day, o: DayOutcome) -> pl.DataFrame:
    s, t = o.inventory.shape
    positions = list(range(t))
    hours = [int(h) for h in day.hours] + [24]
    return pl.DataFrame(
        {
            "date": [day.date] * (s * t),
            "strategy": [o.strategy] * (s * t),
            "station_id": [sid for sid in day.station_ids for _ in positions],
            "position": positions * s,
            "local_hour": hours * s,
            "inventory": o.inventory.reshape(-1),
        }
    )


def travel_for(day: Day, a: Assumptions) -> np.ndarray:
    return travel_minutes(day, a)
