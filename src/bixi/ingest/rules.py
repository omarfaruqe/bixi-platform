"""Cleaning rules and constants (docs/decisions.md, section 8). Change them here only."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = "America/Toronto"  # Montréal's IANA time zone
YEARS = (2023, 2024, 2025)

# Modelled season, local dates: [April 15, November 15). Winter service is excluded.
SEASON_START = (4, 15)
SEASON_END = (11, 15)

FALSE_START_MAX_S = 60  # same-station trips shorter than this are re-docks, not demand
MAX_TRIP_S = 24 * 3600  # longer trips keep their departure but not their arrival

# Raw columns are identical in 2023-2025 (scripts/inspect_raw.py).
RAW_COLUMNS = {
    "STARTSTATIONNAME": "start_name",
    "STARTSTATIONARRONDISSEMENT": "start_borough",
    "STARTSTATIONLATITUDE": "start_lat",
    "STARTSTATIONLONGITUDE": "start_lon",
    "ENDSTATIONNAME": "end_name",
    "ENDSTATIONARRONDISSEMENT": "end_borough",
    "ENDSTATIONLATITUDE": "end_lat",
    "ENDSTATIONLONGITUDE": "end_lon",
    "STARTTIMEMS": "start_ms",
    "ENDTIMEMS": "end_ms",
}


def season_bounds_utc(year: int) -> tuple[datetime, datetime]:
    """Season start (inclusive) and end (exclusive) as UTC instants, from local midnights."""
    tz = ZoneInfo(LOCAL_TZ)
    utc = ZoneInfo("UTC")
    start = datetime.combine(date(year, *SEASON_START), datetime.min.time(), tz)
    end = datetime.combine(date(year, *SEASON_END), datetime.min.time(), tz)
    return start.astimezone(utc), end.astimezone(utc)
