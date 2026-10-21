"""Truck plans that move bikes from stations with a surplus to stations with a deficit.

Two planners, same inputs (bikes to remove or add per station, travel times, the window length):

* ``rule_plan``: a dispatcher's rule of thumb. Serve the station with the largest deficit from the
  nearest station with spare bikes, with whichever truck has the most time left.
* ``optimized_plan``: OR-Tools vehicle routing. Surpluses and deficits are split into chunks of
  a few bikes; each truck's load must stay between 0 and its capacity (so it can only drop bikes it
  has picked up), its route must fit in the window, and every chunk left unserved costs a penalty.
  The solver minimises penalties first and driving time second.

Station indices are 0..S-1; travel-time matrices include the depot at index 0, so station i is
node i + 1 there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from bixi.rebalancing.model import Assumptions, kilometres

CHUNK = 5  # bikes per routing node
SCALE = 10  # OR-Tools needs integers: 1/10 minute resolution
UNSERVED_PENALTY_PER_BIKE = 100 * SCALE  # one unserved bike costs as much as 100 driving minutes


@dataclass
class Stop:
    truck: int
    seq: int
    station: int
    bikes: int  # positive: picked up; negative: dropped off


@dataclass
class Plan:
    stops: list[Stop] = field(default_factory=list)
    drive_minutes: float = 0.0

    def net(self, n_stations: int) -> np.ndarray:
        """Change in bikes per station: pickups remove, drop-offs add."""
        delta = np.zeros(n_stations)
        for s in self.stops:
            delta[s.station] -= s.bikes
        return delta

    @property
    def bikes_moved(self) -> int:
        return sum(s.bikes for s in self.stops if s.bikes > 0)

    def km(self, a: Assumptions) -> float:
        return kilometres(self.drive_minutes, a)


def rule_plan(
    surplus: np.ndarray, deficit: np.ndarray, travel: np.ndarray, a: Assumptions, minutes: float
) -> Plan:
    surplus, deficit = surplus.astype(int).copy(), deficit.astype(int).copy()
    position = [0] * a.trucks  # node index in ``travel`` (0 = depot)
    used = [0.0] * a.trucks
    seq = [0] * a.trucks
    done: set[int] = set()
    plan = Plan()
    while deficit.max(initial=0) > 0 and surplus.max(initial=0) > 0 and len(done) < a.trucks:
        d = int(np.argmax(deficit))
        donors = np.nonzero(surplus > 0)[0]
        s = int(donors[np.argmin(travel[donors + 1, d + 1])])
        truck = min((k for k in range(a.trucks) if k not in done), key=lambda k: used[k])
        q = int(min(a.truck_capacity, surplus[s], deficit[d]))
        drive = travel[position[truck], s + 1] + travel[s + 1, d + 1]
        handling = 2 * a.stop_minutes + 2 * q * a.minutes_per_bike
        if used[truck] + drive + handling + travel[d + 1, 0] > minutes:
            done.add(truck)
            continue
        plan.stops.append(Stop(truck, seq[truck], s, q))
        plan.stops.append(Stop(truck, seq[truck] + 1, d, -q))
        seq[truck] += 2
        used[truck] += drive + handling
        plan.drive_minutes += drive
        position[truck] = d + 1
        surplus[s] -= q
        deficit[d] -= q
    for k in range(a.trucks):  # trucks return to the depot
        plan.drive_minutes += travel[position[k], 0]
    return plan


def optimized_plan(
    surplus: np.ndarray,
    deficit: np.ndarray,
    travel: np.ndarray,
    a: Assumptions,
    minutes: float,
    time_limit_s: float = 1.0,
) -> Plan:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    nodes: list[tuple[int, int]] = [(-1, 0)]  # (station, signed bikes); node 0 is the depot
    for station in np.nonzero(surplus > 0)[0]:
        left = int(surplus[station])
        while left > 0:
            q = min(CHUNK, left)
            nodes.append((int(station), q))
            left -= q
    for station in np.nonzero(deficit > 0)[0]:
        left = int(deficit[station])
        while left > 0:
            q = min(CHUNK, left)
            nodes.append((int(station), -q))
            left -= q
    if not any(q > 0 for _, q in nodes) or not any(q < 0 for _, q in nodes):
        return Plan()

    loc = [0 if s < 0 else s + 1 for s, _ in nodes]
    manager = pywrapcp.RoutingIndexManager(len(nodes), a.trucks, 0)
    routing = pywrapcp.RoutingModel(manager)

    def drive(i: int, j: int) -> int:
        return int(round(travel[loc[i], loc[j]] * SCALE))

    def transit(from_index: int, to_index: int) -> int:
        i, j = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
        service = abs(nodes[i][1]) * a.minutes_per_bike
        stop = a.stop_minutes if loc[i] != loc[j] and j != 0 else 0.0
        return drive(i, j) + int(round((service + stop) * SCALE))

    def arc_cost(from_index: int, to_index: int) -> int:
        return drive(manager.IndexToNode(from_index), manager.IndexToNode(to_index))

    cost_cb = routing.RegisterTransitCallback(arc_cost)
    routing.SetArcCostEvaluatorOfAllVehicles(cost_cb)
    time_cb = routing.RegisterTransitCallback(transit)
    routing.AddDimension(time_cb, 0, int(minutes * SCALE), True, "time")
    load_cb = routing.RegisterUnaryTransitCallback(
        lambda index: nodes[manager.IndexToNode(index)][1]
    )
    routing.AddDimensionWithVehicleCapacity(load_cb, 0, [a.truck_capacity] * a.trucks, True, "load")
    for n in range(1, len(nodes)):
        penalty = abs(nodes[n][1]) * UNSERVED_PENALTY_PER_BIKE
        routing.AddDisjunction([manager.NodeToIndex(n)], penalty)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    solution = routing.SolveWithParameters(params)
    if solution is None:
        return Plan()

    plan = Plan()
    for truck in range(a.trucks):
        index = routing.Start(truck)
        seq = 0
        previous = 0
        while not routing.IsEnd(index):
            index = solution.Value(routing.NextVar(index))
            node = manager.IndexToNode(index)
            plan.drive_minutes += travel[loc[previous], loc[node]]
            previous = node
            if node == 0:
                continue
            station, q = nodes[node]
            # Merge consecutive chunks at the same station into one stop.
            last = plan.stops[-1] if plan.stops else None
            if (
                last
                and last.truck == truck
                and last.station == station
                and (last.bikes > 0) == (q > 0)
            ):
                last.bikes += q
            else:
                plan.stops.append(Stop(truck, seq, station, q))
                seq += 1
    return plan
