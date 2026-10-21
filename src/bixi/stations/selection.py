"""Choose the study stations: continuous history, one compact service zone, a mix of volumes.

Why one zone instead of stations scattered across the island: the rebalancing simulation (Step 8)
routes trucks between the selected stations, which is only realistic inside one service area.
Inside the zone we stratify by volume so the sample is not only the busiest stations, and we
spread picks out geographically so neighbouring stations do not dominate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bixi.stations.identity import OFF_ISLAND, haversine_m

YEARS = (2023, 2024, 2025)

# Zone: 3 km around Sherbrooke / St-Laurent. Covers downtown, Old Montréal and the Old Port,
# the Plateau, McGill / UQAM / Concordia, and parts of Rosemont, Sud-Ouest and Westmount.
ZONE_CENTRE = (45.515, -73.575)
ZONE_RADIUS_M = 3_000.0
MIN_EVENTS_PER_YEAR = 2_000  # starts + ends in each of 2023, 2024 and 2025
# Stability: no year below this share of the station's best year. Large drops mean a relocation,
# a name we could not link, or long construction, all of which would corrupt the history.
MIN_YEAR_RATIO = 0.5
N_STATIONS = 50
CAMPUS_PATTERN = r"(mcgill|uqam|concordia|universit|c[ée]gep|hec|polytechnique|coll[èe]ge)"


@dataclass
class StationHistory:
    """Yearly activity of one live station, summed over all historical names linked to it."""

    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int
    borough: str
    events: dict[int, int] = field(default_factory=dict)  # year -> starts + ends
    historical_names: list[str] = field(default_factory=list)

    @property
    def mean_events(self) -> float:
        return sum(self.events.get(y, 0) for y in YEARS) / len(YEARS)

    @property
    def min_events(self) -> int:
        return min(self.events.get(y, 0) for y in YEARS)

    @property
    def year_ratio(self) -> float:
        """Quietest year divided by busiest year (1.0 = perfectly stable)."""
        busiest = max(self.events.get(y, 0) for y in YEARS)
        return self.min_events / busiest if busiest else 0.0


def station_type(name: str) -> str:
    """Rough category from the name, used to describe the sample (not to select it)."""
    lowered = name.lower()
    if re.search(r"m[ée]tro|gare", lowered):
        return "transit"
    if re.search(CAMPUS_PATTERN, lowered):
        return "campus"
    if re.search(r"\b(parc|square|place|march[ée]|plage|jardin|quai)\b", lowered):
        return "park_plaza"
    return "street"


def eligible(
    stations: list[StationHistory],
    centre: tuple[float, float] = ZONE_CENTRE,
    radius_m: float = ZONE_RADIUS_M,
    min_events: int = MIN_EVENTS_PER_YEAR,
    min_year_ratio: float = MIN_YEAR_RATIO,
) -> list[StationHistory]:
    return [
        s
        for s in stations
        if s.borough not in OFF_ISLAND
        and s.capacity > 0
        and s.min_events >= min_events
        and s.year_ratio >= min_year_ratio
        and haversine_m(s.lat, s.lon, *centre) <= radius_m
    ]


def _farthest_point(pool: list[StationHistory], k: int) -> list[StationHistory]:
    """Greedy max-min spatial spread, seeded with the busiest station. Deterministic."""
    if k >= len(pool):
        return list(pool)
    remaining = sorted(pool, key=lambda s: (-s.mean_events, s.station_id))
    chosen = [remaining.pop(0)]
    nearest = {
        s.station_id: haversine_m(s.lat, s.lon, chosen[0].lat, chosen[0].lon) for s in remaining
    }
    while len(chosen) < k:
        nxt = max(remaining, key=lambda s: (nearest[s.station_id], -s.mean_events, s.station_id))
        remaining.remove(nxt)
        chosen.append(nxt)
        for s in remaining:
            d = haversine_m(s.lat, s.lon, nxt.lat, nxt.lon)
            if d < nearest[s.station_id]:
                nearest[s.station_id] = d
    return chosen


def select_stations(
    candidates: list[StationHistory], n: int = N_STATIONS
) -> list[tuple[StationHistory, str]]:
    """Split candidates into volume terciles and take a spatially spread share of each.

    Returns (station, tier) pairs ordered by tier then busiest first.
    """
    ranked = sorted(candidates, key=lambda s: (s.mean_events, s.station_id))
    if len(ranked) < n:
        raise ValueError(f"only {len(ranked)} eligible stations, need {n}")
    third = len(ranked) // 3
    tiers = {
        "low": ranked[:third],
        "medium": ranked[third : 2 * third],
        "high": ranked[2 * third :],
    }
    quota = {"low": n // 3, "medium": n // 3, "high": n - 2 * (n // 3)}
    picked: list[tuple[StationHistory, str]] = []
    for tier in ("high", "medium", "low"):
        chosen = _farthest_point(tiers[tier], quota[tier])
        picked += [(s, tier) for s in sorted(chosen, key=lambda s: -s.mean_events)]
    return picked
