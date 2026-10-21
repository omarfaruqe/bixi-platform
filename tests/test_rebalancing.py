"""Step 8 tests: inventory simulation, targets, both planners, a full strategy run, summaries."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from bixi.rebalancing.model import Assumptions, Day, simulate, targets, travel_minutes
from bixi.rebalancing.planning import Plan, Stop, rule_plan
from bixi.rebalancing.summary import scenario, summarize


def toy_day(net_a: list[float], net_b: list[float], capacity=(10, 10)) -> Day:
    """Two stations 1 km apart; forecasts equal the actual flows."""
    t = len(net_a)
    arr = np.array([np.clip(net_a, 0, None), np.clip(net_b, 0, None)], dtype=float)
    dep = np.array([np.clip(-np.array(net_a), 0, None), np.clip(-np.array(net_b), 0, None)])
    return Day(
        date=date(2025, 10, 15),
        station_ids=["a", "b"],
        capacity=np.array(capacity, dtype=float),
        lat=np.array([45.500, 45.509]),
        lon=np.array([-73.57, -73.57]),
        hours=np.arange(t),
        dep_fc=dep.copy(),
        arr_fc=arr.copy(),
        dep_actual=dep,
        arr_actual=arr,
        names=["A", "B"],
    )


def test_simulation_counts_empty_and_full_hours():
    day = toy_day([-4, -4, -4], [4, 4, 4])
    result = simulate(day, np.array([5.0, 5.0]), day.net_actual)
    assert result.inventory[:, -1].tolist() == [0.0, 10.0]
    # a: 5 -> 1 -> short 3 -> short 4;  b: 5 -> 9 -> over 3 -> over 4
    assert result.empty_hours == 2 and result.missing_bikes == 7.0
    assert result.full_hours == 2 and result.missing_docks == 7.0


def test_adjustments_are_applied_before_the_hour():
    day = toy_day([-4, -4, -4], [4, 4, 4])
    moves = {1: np.array([7.0, -7.0])}  # a: 1 + 7 = 8 -> 4 -> 0;  b: 9 - 7 = 2 -> 6 -> 10
    result = simulate(day, np.array([5.0, 5.0]), day.net_actual, moves)
    assert result.empty_hours == 0 and result.full_hours == 0


def test_targets_keep_the_forecast_path_inside_the_docks():
    capacity = np.array([10.0, 10.0, 10.0])
    net = np.array([[-3, -3, 0], [3, 3, 0], [8, -8, 0]], dtype=float)
    start = np.array([2.0, 7.0, 5.0])
    t = targets(start, net, capacity)
    assert t[0] == 6.0  # needs at least 6 bikes for 6 departures
    assert t[1] == 4.0  # needs room for 6 arrivals
    assert t[2] == 2.0  # +8 then -8: anything in [0, 2] works; nearest to 5 is 2
    swing = targets(np.array([5.0]), np.array([[15.0, -15.0]]), np.array([10.0]))
    assert swing[0] == 0.0  # infeasible: middle of [0, -5] clipped to the docks


def test_travel_matrix_is_symmetric_with_depot_first():
    day = toy_day([0], [0])
    m = travel_minutes(day, Assumptions())
    assert m.shape == (3, 3) and np.allclose(m, m.T) and np.all(np.diag(m) == 0)
    # 1 km apart, x1.3 detour at 18 km/h = 4.3 minutes
    assert m[1, 2] == pytest.approx(1.0 * 1.3 / 18 * 60, rel=0.02)


def test_plan_net_and_bikes_moved():
    plan = Plan([Stop(0, 0, 1, 7), Stop(0, 1, 0, -7)])
    assert plan.net(2).tolist() == [7.0, -7.0] and plan.bikes_moved == 7


def test_rule_plan_respects_truck_capacity_and_time():
    day = toy_day([0], [0])
    travel = travel_minutes(day, Assumptions())
    a = Assumptions(trucks=1, truck_capacity=20)
    plan = rule_plan(np.array([0, 30]), np.array([30, 0]), travel, a, minutes=120)
    assert plan.bikes_moved == 30 and all(abs(s.bikes) <= 20 for s in plan.stops)
    nothing = rule_plan(np.array([0, 30]), np.array([30, 0]), travel, a, minutes=5)
    assert nothing.bikes_moved == 0  # one round trip does not fit in 5 minutes


def test_optimized_plan_moves_bikes_without_exceeding_capacity():
    pytest.importorskip("ortools")
    from bixi.rebalancing.planning import optimized_plan

    day = toy_day([0], [0])
    travel = travel_minutes(day, Assumptions())
    a = Assumptions(trucks=1, truck_capacity=20)
    plan = optimized_plan(np.array([0, 12]), np.array([12, 0]), travel, a, 120, time_limit_s=0.5)
    assert plan.bikes_moved == 12
    assert plan.net(2).tolist() == [12.0, -12.0]
    load = 0
    for s in sorted(plan.stops, key=lambda s: s.seq):
        load += s.bikes
        assert 0 <= load <= a.truck_capacity
    assert optimized_plan(np.array([0, 0]), np.array([5, 0]), travel, a, 120).bikes_moved == 0


def test_strategies_reduce_problem_hours_on_a_commuting_day():
    pytest.importorskip("ortools")
    from bixi.rebalancing.run import run_strategy

    # Station a empties every hour after 7 h, station b fills: rebalancing at 5-7 h must help.
    net_a = [0.0] * 7 + [-3.0] * 5 + [0.0] * 12
    net_b = [0.0] * 7 + [3.0] * 5 + [0.0] * 12
    day = toy_day(net_a, net_b, capacity=(20, 20))
    a = Assumptions(start_fill=0.5, trucks=1)  # a needs 15 bikes, b needs 15 free docks
    travel = travel_minutes(day, a)
    none = run_strategy(day, a, "none", travel)
    rule = run_strategy(day, a, "rule_forecast", travel)
    opt = run_strategy(day, a, "optimized_forecast", travel, time_limit_s=0.5)
    assert none.empty_hours > 0
    assert rule.empty_hours + rule.full_hours < none.empty_hours + none.full_hours
    assert opt.empty_hours + opt.full_hours <= rule.empty_hours + rule.full_hours
    assert opt.bikes_moved > 0 and opt.truck_km > 0


def test_summary_reduction_and_share_of_oracle():
    results = pl.DataFrame(
        {
            "date": [date(2025, 10, 1)] * 4,
            "start_fill": [0.5] * 4,
            "trucks": [2] * 4,
            "strategy": ["none", "rule_forecast", "optimized_forecast", "optimized_oracle"],
            "empty_hours": [60, 50, 40, 35],
            "full_hours": [40, 35, 30, 25],
            "problem_hours": [100, 85, 70, 60],
            "missing_bikes": [1.0] * 4,
            "missing_docks": [1.0] * 4,
            "bikes_moved": [0, 50, 80, 85],
            "truck_km": [0.0, 60.0, 50.0, 48.0],
            "unmet_target_bikes": [0, 10, 5, 4],
        }
    )
    s = scenario(summarize(results), 0.5, 2)
    rows = {r["strategy"]: r for r in s.iter_rows(named=True)}
    assert s["strategy"].to_list()[0] == "none"
    assert rows["optimized_forecast"]["reduction"] == pytest.approx(0.30)
    assert rows["optimized_forecast"]["share_of_oracle"] == pytest.approx(0.75)


def test_dashboard_modules_do_not_import_ortools():
    """The server image has no OR-Tools: the page must only read precomputed results."""
    import subprocess
    import sys

    code = (
        "import sys, bixi.app.views.rebalancing, bixi.app.rebalancing_charts; "
        "sys.exit('ortools' in sys.modules)"
    )
    import os
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([src, os.environ.get("PYTHONPATH", "")])}
    assert subprocess.run([sys.executable, "-c", code], env=env, check=False).returncode == 0
