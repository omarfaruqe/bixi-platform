"""Link historical station names to live stations and choose the 50 study stations (Step 2).

Inputs (produced earlier in Step 2):
    data/processed/station_summary.csv                one row per historical station name
    data/raw/gbfs/station_information_*.json          live feed; the newest file is used
Outputs:
    data/processed/station_crosswalk.csv              every historical name -> live station_id
    data/processed/station_selection.txt              the report (selection criteria and mix)
    reference/selected_stations.csv                   the 50 stations; committed to git

Usage, from the project root:
    python scripts/select_stations.py
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bixi.stations.identity import (  # noqa: E402
    MAX_LINK_DISTANCE_M,
    link_names,
    parse_gbfs_station_information,
)
from bixi.stations.selection import (  # noqa: E402
    MIN_EVENTS_PER_YEAR,
    MIN_YEAR_RATIO,
    N_STATIONS,
    YEARS,
    ZONE_CENTRE,
    ZONE_RADIUS_M,
    StationHistory,
    eligible,
    select_stations,
    station_type,
)

SUMMARY = ROOT / "data/processed/station_summary.csv"
GBFS_DIR = ROOT / "data/raw/gbfs"
CROSSWALK = ROOT / "data/processed/station_crosswalk.csv"
REPORT = ROOT / "data/processed/station_selection.txt"
SELECTED = ROOT / "reference/selected_stations.csv"


def to_float(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def counts(values) -> str:
    return ", ".join(f"{k} {v}" for k, v in Counter(values).most_common())


def main() -> None:
    feeds = sorted(GBFS_DIR.glob("station_information_*.json"))
    if not feeds:
        sys.exit("No GBFS station_information file. Run the download step first.")
    live = parse_gbfs_station_information(json.loads(feeds[-1].read_text(encoding="utf-8")))
    live_by_id = {s.station_id: s for s in live}

    with SUMMARY.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    links = link_names(
        ((r["station_name"], to_float(r["lat_median"]), to_float(r["lon_median"])) for r in rows),
        live,
    )

    # Crosswalk for the whole network (Step 3 uses it to attach station_id to every trip).
    CROSSWALK.parent.mkdir(parents=True, exist_ok=True)
    with CROSSWALK.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["historical_name", "station_id", "live_name", "distance_m"])
        for link in links:
            dist = "" if link.distance_m is None else f"{link.distance_m:.1f}"
            writer.writerow(
                [link.historical_name, link.station_id or "", link.live_name or "", dist]
            )

    # Sum yearly events per live station across all linked historical names.
    histories: dict[str, StationHistory] = {}
    borough_votes: dict[str, Counter] = defaultdict(Counter)
    events_total = {y: 0 for y in YEARS}
    events_linked = {y: 0 for y in YEARS}
    for row, link in zip(rows, links, strict=True):
        yearly = {y: int(row[f"starts_{y}"]) + int(row[f"ends_{y}"]) for y in YEARS}
        for y in YEARS:
            events_total[y] += yearly[y]
        if link.station_id is None:
            continue
        for y in YEARS:
            events_linked[y] += yearly[y]
        s = live_by_id[link.station_id]
        h = histories.setdefault(
            s.station_id, StationHistory(s.station_id, s.name, s.lat, s.lon, s.capacity, "")
        )
        for y in YEARS:
            h.events[y] = h.events.get(y, 0) + yearly[y]
        h.historical_names.append(row["station_name"])
        borough_votes[s.station_id][row["borough"]] += sum(yearly.values())
    for sid, h in histories.items():
        h.borough = borough_votes[sid].most_common(1)[0][0]

    pool = eligible(list(histories.values()))
    picked = select_stations(pool)

    SELECTED.parent.mkdir(parents=True, exist_ok=True)
    with SELECTED.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "station_id",
                "name",
                "borough",
                "lat",
                "lon",
                "capacity",
                "volume_tier",
                "station_type",
                "events_2023",
                "events_2024",
                "events_2025",
                "historical_names",
            ]
        )
        for s, tier in picked:
            writer.writerow(
                [
                    s.station_id,
                    s.name,
                    s.borough,
                    f"{s.lat:.6f}",
                    f"{s.lon:.6f}",
                    s.capacity,
                    tier,
                    station_type(s.name),
                    s.events[2023],
                    s.events[2024],
                    s.events[2025],
                    " | ".join(sorted(set(s.historical_names))),
                ]
            )

    capacities = [s.capacity for s, _ in picked]
    linked_names = sum(1 for link in links if link.station_id)
    lines = [
        "BIXI station identity and selection",
        f"live feed: {feeds[-1].name} ({len(live):,} stations with docks)",
        "",
        "--- Linking historical names to live stations ---",
        f"historical names: {len(rows):,}; linked within {MAX_LINK_DISTANCE_M:.0f} m: "
        f"{linked_names:,}; live stations with history: {len(histories):,}",
        "share of trip events at linked names: "
        + ", ".join(f"{y} {events_linked[y] / events_total[y]:.1%}" for y in YEARS),
        f"live stations with more than one historical name: "
        f"{sum(1 for h in histories.values() if len(set(h.historical_names)) > 1):,}",
        "",
        "--- Selection ---",
        f"zone: {ZONE_RADIUS_M / 1000:.0f} km around {ZONE_CENTRE}; island boroughs only; "
        f"at least {MIN_EVENTS_PER_YEAR:,} events in each of {YEARS}; "
        f"no year below {MIN_YEAR_RATIO:.0%} of the busiest year",
        f"eligible stations: {len(pool)}; selected: {len(picked)} (target {N_STATIONS})",
        "volume tiers: " + ", ".join(f"{k} {v}" for k, v in Counter(t for _, t in picked).items()),
        "station types: " + counts(station_type(s.name) for s, _ in picked),
        "boroughs: " + counts(s.borough for s, _ in picked),
        f"capacity: min {min(capacities)}, max {max(capacities)}, total {sum(capacities):,} docks",
        "",
        f"{'id':>5}  {'tier':<6}  {'type':<10}  {'cap':>3}  "
        f"{'ev2023':>7}  {'ev2024':>7}  {'ev2025':>7}  name",
    ]
    for s, tier in picked:
        lines.append(
            f"{s.station_id:>5}  {tier:<6}  {station_type(s.name):<10}  {s.capacity:>3}  "
            f"{s.events[2023]:>7,}  {s.events[2024]:>7,}  {s.events[2025]:>7,}  {s.name}"
        )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    written = ", ".join(str(p.relative_to(ROOT)) for p in (CROSSWALK, SELECTED, REPORT))
    print(f"\nWrote {written}")


if __name__ == "__main__":
    main()
