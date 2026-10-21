"""Major Montréal events (reference/events.csv) as station-day features.

Dates are published months in advance, so using them for a 24-hour forecast is not leakage.
Two features per station and local date:

* ``event_any``: 1 when any listed event runs in the city that day.
* ``event_distance_km``: distance from the station to the nearest venue with an event that day
  (null when there is none). Trees can learn "within about 1 km of the Quartier des spectacles
  during a festival" from this without a hand-picked radius.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import polars as pl

from bixi.stations.identity import haversine_m


def load_events(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, try_parse_dates=True)


def event_days(events: pl.DataFrame) -> pl.DataFrame:
    """One row per event and local date it runs."""
    rows = []
    for event in events.iter_rows(named=True):
        day = event["start_date"]
        while day <= event["end_date"]:
            rows.append(
                {
                    "local_date": day,
                    "event": event["event"],
                    "lat": event["lat"],
                    "lon": event["lon"],
                }
            )
            day += timedelta(days=1)
    return pl.DataFrame(
        rows,
        schema={"local_date": pl.Date, "event": pl.String, "lat": pl.Float64, "lon": pl.Float64},
    )


def station_event_features(events: pl.DataFrame, stations: pl.DataFrame) -> pl.DataFrame:
    """station_id x local_date rows for days with at least one event."""
    days = event_days(events)
    if days.is_empty():
        return pl.DataFrame(
            schema={
                "station_id": pl.String,
                "local_date": pl.Date,
                "event_any": pl.Int8,
                "event_distance_km": pl.Float64,
            }
        )
    pairs = stations.select(
        "station_id", pl.col("lat").alias("s_lat"), pl.col("lon").alias("s_lon")
    )
    joined = days.join(pairs, how="cross")
    distance = [
        haversine_m(a, b, c, d) / 1000
        for a, b, c, d in joined.select("s_lat", "s_lon", "lat", "lon").iter_rows()
    ]
    return (
        joined.with_columns(distance_km=pl.Series(distance))
        .group_by("station_id", "local_date")
        .agg(pl.col("distance_km").min().alias("event_distance_km"))
        .with_columns(event_any=pl.lit(1, dtype=pl.Int8))
        .select("station_id", "local_date", "event_any", "event_distance_km")
    )
