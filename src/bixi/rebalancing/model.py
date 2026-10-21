"""Assumptions, the day's data, travel times, inventory simulation and target inventories.

Everything here is an explicit assumption, because historical trips cannot tell us how many bikes
were docked at a station: starting inventory, dock counts (live GBFS capacity, no staffed overflow
docking), truck capacity, speeds and handling times.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from bixi.stations.identity import haversine_m


@dataclass(frozen=True)
class Assumptions:
    start_fill: float = 0.5  # share of docks holding a bike at midnight
    trucks: int = 2
    truck_capacity: int = 20  # bikes per truck
    speed_kmh: float = 18.0  # average urban truck speed
    detour_factor: float = 1.3  # road distance / straight-line distance
    stop_minutes: float = 4.0  # parking and walking, per station visited
    minutes_per_bike: float = 0.5  # loading or unloading one bike
    # Rebalancing windows (local hours, start inclusive, end exclusive). Moves planned at the
    # start of a window take effect at its end; each plan covers the hours until the next window.
    windows: tuple[tuple[int, int], ...] = ((5, 7), (13, 15))

    def window_minutes(self, window: tuple[int, int]) -> float:
        return (window[1] - window[0]) * 60.0


@dataclass
class Day:
    """One local day: per-station hourly flows (forecast and actual) and station attributes."""

    date: object
    station_ids: list[str]
    capacity: np.ndarray  # (S,)
    lat: np.ndarray
    lon: np.ndarray
    hours: np.ndarray  # (T,) local hour of each position (25 positions on the DST day)
    dep_fc: np.ndarray  # (S, T)
    arr_fc: np.ndarray
    dep_actual: np.ndarray
    arr_actual: np.ndarray
    names: list[str] = field(default_factory=list)

    @property
    def net_fc(self) -> np.ndarray:
        return self.arr_fc - self.dep_fc

    @property
    def net_actual(self) -> np.ndarray:
        return self.arr_actual - self.dep_actual


def build_day(forecasts: pl.DataFrame, stations: pl.DataFrame, day) -> Day:
    """``forecasts`` is a Step 7 run file (station_id, target, ts_utc, local_hour, yhat, actual)."""
    rows = forecasts.filter(pl.col("local_date") == day)
    meta = stations.sort("station_id")
    ids = meta["station_id"].to_list()
    times = rows.select("ts_utc", "local_hour").unique().sort("ts_utc")
    position = {ts: i for i, ts in enumerate(times["ts_utc"].to_list())}
    index = {sid: i for i, sid in enumerate(ids)}
    shape = (len(ids), times.height)
    arrays = {k: np.zeros(shape) for k in ("dep_fc", "arr_fc", "dep_actual", "arr_actual")}
    for r in rows.iter_rows(named=True):
        if r["station_id"] not in index:
            continue
        i, t = index[r["station_id"]], position[r["ts_utc"]]
        prefix = "dep" if r["target"] == "departures" else "arr"
        arrays[f"{prefix}_fc"][i, t] = r["yhat"]
        arrays[f"{prefix}_actual"][i, t] = r["actual"] or 0.0
    return Day(
        date=day,
        station_ids=ids,
        capacity=meta["capacity"].to_numpy().astype(float),
        lat=meta["lat"].to_numpy(),
        lon=meta["lon"].to_numpy(),
        hours=times["local_hour"].to_numpy(),
        names=meta["name"].to_list() if "name" in meta.columns else ids,
        **arrays,
    )


def travel_minutes(day: Day, a: Assumptions) -> np.ndarray:
    """(S+1, S+1) driving minutes; index 0 is the depot at the stations' centroid."""
    lat = np.concatenate([[day.lat.mean()], day.lat])
    lon = np.concatenate([[day.lon.mean()], day.lon])
    n = lat.size
    out = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            km = haversine_m(lat[i], lon[i], lat[j], lon[j]) / 1000 * a.detour_factor
            out[i, j] = out[j, i] = km / a.speed_kmh * 60.0
    return out


@dataclass
class SimResult:
    inventory: np.ndarray  # (S, T+1) bikes at the start of each position, plus the end of day
    empty_hours: int  # station-hours with departures that found no bike
    full_hours: int  # station-hours with arrivals that found no free dock
    missing_bikes: float  # departures that could not happen
    missing_docks: float  # arrivals that could not dock


def simulate(
    day: Day, start: np.ndarray, net: np.ndarray, adjustments: dict[int, np.ndarray] | None = None
) -> SimResult:
    """Hourly inventory with dock limits. ``adjustments[t]`` is added just before position t.

    Within an hour, departures and arrivals are netted (hourly data has no finer order), which
    understates problems at busy stations. Observed flows are themselves censored.
    """
    adjustments = adjustments or {}
    s, t_max = net.shape
    inv = np.zeros((s, t_max + 1))
    inv[:, 0] = start
    empty = full = 0
    missing_bikes = missing_docks = 0.0
    for t in range(t_max):
        current = inv[:, t] + adjustments.get(t, 0.0)
        current = np.clip(current, 0.0, day.capacity)
        inv[:, t] = current
        nxt = current + net[:, t]
        short = np.clip(-nxt, 0.0, None)
        over = np.clip(nxt - day.capacity, 0.0, None)
        empty += int((short > 0.5).sum())
        full += int((over > 0.5).sum())
        missing_bikes += float(short.sum())
        missing_docks += float(over.sum())
        inv[:, t + 1] = np.clip(nxt, 0.0, day.capacity)
    return SimResult(inv, empty, full, missing_bikes, missing_docks)


def targets(start_inventory: np.ndarray, net: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    """Inventory each station should have so its forecast path stays within [0, capacity].

    With prefix sums P of the forecast net flow, the path stays feasible for x in
    [max(0, -min P), min(C, C - max P)]. If the current inventory is inside, keep it (no move);
    otherwise move to the nearest end. When no x is feasible (the swing exceeds the station),
    aim for the middle so shortages and overflows are split.
    """
    if net.shape[1] == 0:
        return start_inventory.copy()
    prefix = np.cumsum(net, axis=1)
    low = np.maximum(0.0, -prefix.min(axis=1))
    high = np.minimum(capacity, capacity - prefix.max(axis=1))
    feasible = low <= high
    target = np.where(feasible, np.clip(start_inventory, low, high), (low + high) / 2.0)
    return np.clip(np.round(target), 0.0, capacity)


def hour_positions(day: Day, hour: int) -> int:
    """First position whose local hour is ``hour`` (or the end of day)."""
    matches = np.nonzero(day.hours == hour)[0]
    return int(matches[0]) if matches.size else len(day.hours)


def kilometres(minutes: float, a: Assumptions) -> float:
    return minutes / 60.0 * a.speed_kmh
