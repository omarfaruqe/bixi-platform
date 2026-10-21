"""Station identity and selection tests (no data files needed)."""

from __future__ import annotations

from bixi.stations.identity import (
    LiveStation,
    haversine_m,
    link_names,
    normalize_name,
    parse_gbfs_station_information,
    valid_coordinate,
)
from bixi.stations.selection import (
    StationHistory,
    eligible,
    select_stations,
    station_type,
)


def test_normalize_name_ignores_case_accents_and_spacing():
    assert normalize_name("1ère  avenue / Jean-Talon") == normalize_name("1ere avenue / Jean-talon")
    assert normalize_name("de l'Hôtel-de-Ville / Rachel") == "de l'hotel-de-ville / rachel"


def test_haversine_known_distance():
    # One thousandth of a degree of latitude is about 111 m.
    assert 110 < haversine_m(45.500, -73.570, 45.501, -73.570) < 112


def test_sentinel_coordinates_are_invalid():
    assert not valid_coordinate(0.0, 0.0)
    assert not valid_coordinate(-1.0, -1.0)
    assert not valid_coordinate(None, -73.5)
    assert valid_coordinate(45.52, -73.58)


def test_link_names_uses_nearest_station_within_threshold():
    live = [
        LiveStation("1", "A", 45.5000, -73.5700, 20),
        LiveStation("2", "B", 45.5100, -73.5700, 20),
    ]
    links = link_names(
        [
            ("old A", 45.5002, -73.5700),  # ~22 m from A
            ("far", 45.5050, -73.5700),  # ~550 m from both
            ("broken", 0.0, 0.0),
        ],
        live,
    )
    assert links[0].station_id == "1"
    assert links[1].station_id is None and links[1].distance_m > 500
    assert links[2].station_id is None and links[2].distance_m is None


def test_gbfs_parser_skips_swap_and_zero_capacity():
    payload = {
        "data": {
            "stations": [
                {"station_id": "1", "name": "Real", "lat": 45.5, "lon": -73.5, "capacity": 23},
                {"station_id": "36", "name": "6037_SWAP", "lat": 45.5, "lon": -73.5, "capacity": 0},
                {"station_id": "9", "name": "Empty", "lat": 45.5, "lon": -73.5, "capacity": 0},
            ]
        }
    }
    assert [s.station_id for s in parse_gbfs_station_information(payload)] == ["1"]


def test_station_type():
    assert station_type("Métro Peel (de Maisonneuve / Stanley)") == "transit"
    assert station_type("Parc Beaubien (Beaubien / 8e avenue)") == "park_plaza"
    assert station_type("Laurier / St-Denis") == "street"


def _grid(n: int) -> list[StationHistory]:
    stations = []
    for i in range(n):
        lat = 45.505 + (i % 10) * 0.002
        lon = -73.585 + (i // 10) * 0.003
        ev = 3_000 + i * 500
        stations.append(
            StationHistory(
                str(i), f"S{i}", lat, lon, 20, "Ville-Marie", {2023: ev, 2024: ev, 2025: ev}
            )
        )
    return stations


def test_eligible_filters_volume_stability_borough_and_zone():
    stations = _grid(6)
    stations[0].events[2024] = 100  # gap year
    stations[1].borough = "Laval"
    stations[2].lat = 45.70  # far outside the zone
    stations[3].events[2025] = 2_100  # above the floor, but a drop of more than half
    assert [s.station_id for s in eligible(stations)] == ["4", "5"]


def test_selection_is_deterministic_and_balanced_by_tier():
    pool = _grid(90)
    first = select_stations(pool, n=30)
    second = select_stations(list(reversed(pool)), n=30)
    assert [s.station_id for s, _ in first] == [s.station_id for s, _ in second]
    tiers = [t for _, t in first]
    assert len(first) == 30 and len({s.station_id for s, _ in first}) == 30
    assert tiers.count("high") == tiers.count("medium") == tiers.count("low") == 10
