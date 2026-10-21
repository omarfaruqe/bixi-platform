"""Link historical station names to live GBFS stations by distance.

Pure standard library so it can be tested without the data stack.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

EARTH_RADIUS_M = 6_371_000.0
# A historical name within this distance of a live station is treated as that station.
MAX_LINK_DISTANCE_M = 50.0

# Trip files and the station summary also contain municipalities outside the island of Montréal
# (BIXI expanded to Laval, the South Shore and Sherbrooke). They are out of scope.
OFF_ISLAND = frozenset(
    {
        "Laval",
        "Longueuil",
        "Le Vieux-Longueuil",
        "Sherbrooke",
        "Saint-Eustache",
        "Deux-Montagnes",
        "Boucherville",
        "Sainte-Julie",
        "Saint-Lambert",
        "Terrebonne",
    }
)


def normalize_name(name: str) -> str:
    """Comparison key for a station name: no accents, lower case, single spaces.

    Only used for diagnostics and matching; the displayed name is never altered.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().casefold()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def valid_coordinate(lat: float | None, lon: float | None) -> bool:
    """False for missing values and the 0.0 / -1.0 sentinels found in the raw files."""
    if lat is None or lon is None:
        return False
    return 44.0 < lat < 47.0 and -75.0 < lon < -70.0


@dataclass(frozen=True)
class LiveStation:
    station_id: str
    name: str
    lat: float
    lon: float
    capacity: int


@dataclass(frozen=True)
class Link:
    historical_name: str
    station_id: str | None  # None when no live station is within the threshold
    live_name: str | None
    distance_m: float | None


def link_names(
    names: Iterable[tuple[str, float | None, float | None]],
    live: list[LiveStation],
    max_distance_m: float = MAX_LINK_DISTANCE_M,
) -> list[Link]:
    """Link each (name, lat, lon) to its nearest live station within ``max_distance_m``.

    1,700 names x 1,100 stations is small enough for a direct nearest-neighbour search.
    """
    links: list[Link] = []
    for name, lat, lon in names:
        if not valid_coordinate(lat, lon) or not live:
            links.append(Link(name, None, None, None))
            continue
        best = min(live, key=lambda s: haversine_m(lat, lon, s.lat, s.lon))
        distance = haversine_m(lat, lon, best.lat, best.lon)
        if distance <= max_distance_m:
            links.append(Link(name, best.station_id, best.name, distance))
        else:
            links.append(Link(name, None, None, distance))
    return links


def parse_gbfs_station_information(payload: dict) -> list[LiveStation]:
    """Read the GBFS ``station_information`` feed, skipping test/SWAP entries with no docks."""
    stations = []
    for row in payload["data"]["stations"]:
        capacity = int(row.get("capacity") or 0)
        if capacity <= 0 or "SWAP" in row["name"].upper():
            continue
        stations.append(
            LiveStation(
                station_id=str(row["station_id"]),
                name=row["name"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                capacity=capacity,
            )
        )
    return stations
