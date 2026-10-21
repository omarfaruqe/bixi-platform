"""Profile and validate the raw BIXI trips (Step 2, stage 2).

What the raw files look like (from scripts/inspect_raw.py): 10 columns, identical in 2023-2025,
NO station id (only name, borough, lat/lon), and times as epoch MILLISECONDS (UTC instants).
This script answers the questions that decide the cleaning rules and the choice of 50 stations:

  * Do the files cover what we think (months, local-time boundaries)?
  * How many trips have no end (so no arrival), zero coordinates, or odd durations?
  * Is a station name a stable identifier, or do names/coordinates drift between years?
  * Which stations are continuous across 2023-2025?
  * How well do the live GBFS stations match the historical names?

Usage (project root, after:  pip install -e ".[data]"):
    python scripts/profile_trips.py            # reads data/raw, writes data/processed/
Outputs:
    data/processed/trip_profile.txt       the report (paste this back)
    data/processed/station_summary.csv    one row per station name
    data/processed/bixi_profile.duckdb    scratch database (safe to delete)
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

RAW_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw")
OUT_DIR = Path("data/processed")
YEARS = (2023, 2024, 2025)
MIN_EVENTS = 500  # a station counts as "present" in a year with at least this many starts+ends
TIMEZONE = "America/Toronto"  # Montréal's IANA timezone


def literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def fmt(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def show(con: duckdb.DuckDBPyConnection, lines: list[str], title: str, sql: str) -> None:
    lines.append(f"\n--- {title} ---")
    cursor = con.execute(sql)
    columns = [column[0] for column in cursor.description]
    rows = [[fmt(value) for value in row] for row in cursor.fetchall()]
    widths = [max([len(name)] + [len(row[i]) for row in rows]) for i, name in enumerate(columns)]
    lines.append("  ".join(name.ljust(width) for name, width in zip(columns, widths, strict=True)))
    for row in rows:
        lines.append("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)))


CREATE_TRIPS = r"""
CREATE OR REPLACE TABLE trips AS
SELECT
    CAST(regexp_extract(filename, '([0-9]{4})[/\\][^/\\]*$', 1) AS INTEGER) AS file_year,
    STARTSTATIONNAME AS start_station_name,
    STARTSTATIONARRONDISSEMENT AS start_borough,
    NULLIF(STARTSTATIONLATITUDE, 0) AS start_lat,
    NULLIF(STARTSTATIONLONGITUDE, 0) AS start_lon,
    ENDSTATIONNAME AS end_station_name,
    ENDSTATIONARRONDISSEMENT AS end_borough,
    NULLIF(ENDSTATIONLATITUDE, 0) AS end_lat,
    NULLIF(ENDSTATIONLONGITUDE, 0) AS end_lon,
    STARTTIMEMS AS start_ms,
    ENDTIMEMS AS end_ms,
    timezone('__TZ__', to_timestamp(STARTTIMEMS / 1000.0)) AS start_local,
    timezone('__TZ__', to_timestamp(ENDTIMEMS / 1000.0)) AS end_local,
    (ENDTIMEMS - STARTTIMEMS) / 1000.0 AS duration_s
FROM read_csv('__GLOB__', header=true, sample_size=-1, filename=true, ignore_errors=true)
"""

CREATE_EVENTS = """
CREATE OR REPLACE VIEW events AS
SELECT 'start' AS direction, start_station_name AS station_name, start_borough AS borough,
       start_lat AS lat, start_lon AS lon, start_local AS ts_local
FROM trips WHERE start_station_name IS NOT NULL
UNION ALL
SELECT 'end', end_station_name, end_borough, end_lat, end_lon, end_local
FROM trips WHERE end_station_name IS NOT NULL
"""


def build_station_summary_sql(out_path: Path) -> str:
    per_year = ",\n    ".join(
        f"count(*) FILTER (WHERE direction = 'start' AND year(ts_local) = {y}) AS starts_{y},\n"
        f"    count(*) FILTER (WHERE direction = 'end' AND year(ts_local) = {y}) AS ends_{y}"
        for y in YEARS
    )
    return f"""
COPY (
  SELECT station_name,
    mode(borough) AS borough,
    median(lat) AS lat_median,
    median(lon) AS lon_median,
    {per_year},
    min(ts_local) AS first_event_local,
    max(ts_local) AS last_event_local,
    count(DISTINCT date_trunc('month', ts_local)) AS active_months
  FROM events
  GROUP BY station_name
  ORDER BY station_name
) TO {literal(out_path.as_posix())} (HEADER, DELIMITER ',')
"""


def continuity_sql() -> str:
    flags = ",\n      ".join(
        f"max(CASE WHEN y = {y} AND n >= {MIN_EVENTS} THEN 1 ELSE 0 END) AS present_{y}"
        for y in YEARS
    )
    columns = ", ".join(f"present_{y}" for y in YEARS)
    return f"""
WITH per AS (
  SELECT station_name, year(ts_local) AS y, count(*) AS n FROM events GROUP BY 1, 2
), wide AS (
  SELECT station_name,
      {flags}
  FROM per GROUP BY station_name
)
SELECT {columns}, count(*) AS station_names FROM wide GROUP BY {columns} ORDER BY {columns} DESC
"""


def main() -> int:
    csv_files = sorted(RAW_DIR.glob("trips/*/*.csv"))
    if not csv_files:
        print(f"No CSV files under {RAW_DIR}/trips/<year>/. Run: python -m bixi.download trips")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(OUT_DIR / "bixi_profile.duckdb"))
    try:
        con.execute("LOAD icu")
    except duckdb.Error:
        pass  # already built in for most installs

    print("Loading trips (a minute or two for ~16M rows)...")
    glob = (RAW_DIR / "trips" / "*" / "*.csv").as_posix()
    create_trips = CREATE_TRIPS.replace("__GLOB__", glob.replace("'", "''"))
    con.execute(create_trips.replace("__TZ__", TIMEZONE))
    con.execute(CREATE_EVENTS)

    lines = [f"BIXI trip profile ({len(csv_files)} file(s); local time = {TIMEZONE})"]

    show(con, lines, "1. Coverage by file (local time)", """
        SELECT file_year, count(*) AS trips,
               min(start_local) AS first_start, max(start_local) AS last_start,
               sum(CAST(year(start_local) <> file_year AS INTEGER)) AS start_year_mismatch
        FROM trips GROUP BY 1 ORDER BY 1""")

    show(con, lines, "2. Trips per month (local) and share without an end time", """
        SELECT file_year, month(start_local) AS month, count(*) AS trips,
               round(100.0 * avg(CAST(end_ms IS NULL AS INTEGER)), 1) AS pct_no_end
        FROM trips GROUP BY 1, 2 ORDER BY 1, 2""")

    show(con, lines, "3. Data-quality counts by file", """
        SELECT file_year, count(*) AS trips,
               sum(CAST(end_ms IS NULL AS INTEGER)) AS no_end_time,
               sum(CAST(end_station_name IS NULL AS INTEGER)) AS no_end_station,
               sum(CAST(end_ms IS NOT NULL AND end_station_name IS NULL AS INTEGER))
                   AS end_time_but_no_station,
               sum(CAST(start_station_name IS NULL AS INTEGER)) AS no_start_station,
               sum(CAST(start_lat IS NULL OR start_lon IS NULL AS INTEGER)) AS start_coords_missing,
               sum(CAST(end_station_name IS NOT NULL AND (end_lat IS NULL OR end_lon IS NULL)
                   AS INTEGER)) AS end_coords_missing,
               sum(CAST(start_station_name = end_station_name AS INTEGER)) AS same_start_end
        FROM trips GROUP BY 1 ORDER BY 1""")

    show(con, lines, "4. Trip duration (seconds unless noted)", """
        SELECT file_year, count(duration_s) AS with_duration,
               round(min(duration_s), 0) AS min_s,
               round(quantile_cont(duration_s, 0.01), 0) AS p01,
               round(quantile_cont(duration_s, 0.05), 0) AS p05,
               round(quantile_cont(duration_s, 0.50), 0) AS p50,
               round(quantile_cont(duration_s, 0.95), 0) AS p95,
               round(quantile_cont(duration_s, 0.99), 0) AS p99,
               round(max(duration_s) / 3600.0, 1) AS max_hours,
               sum(CAST(duration_s <= 0 AS INTEGER)) AS nonpositive,
               sum(CAST(duration_s > 0 AND duration_s < 60 AS INTEGER)) AS under_1_min,
               sum(CAST(duration_s > 86400 AS INTEGER)) AS over_24h,
               sum(CAST(duration_s > 7 * 86400 AS INTEGER)) AS over_7_days
        FROM trips WHERE duration_s IS NOT NULL GROUP BY 1 ORDER BY 1""")

    show(con, lines, "5. Starts by local hour (expect commute peaks near 8h and 17-18h)", """
        SELECT hour(start_local) AS hour, count(*) AS trips,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
        FROM trips GROUP BY 1 ORDER BY 1""")

    show(con, lines, "6. Station names per year (events = starts + ends)", f"""
        WITH per AS (
          SELECT year(ts_local) AS year, station_name, count(*) AS n FROM events GROUP BY 1, 2)
        SELECT year, count(*) AS station_names,
               sum(CAST(n >= {MIN_EVENTS} AS INTEGER)) AS names_with_{MIN_EVENTS}_plus_events
        FROM per GROUP BY 1 ORDER BY 1""")

    clusters = """
        WITH c AS (
          SELECT station_name, round(lat, 3) AS lat3, round(lon, 3) AS lon3, count(*) AS n
          FROM events WHERE lat IS NOT NULL GROUP BY 1, 2, 3),
        s AS (
          SELECT station_name, count(*) AS coord_clusters, sum(n) AS events,
                 round(max(n) * 1.0 / sum(n), 3) AS dominant_share,
                 round(sqrt(pow((max(lat3) - min(lat3)) * 111000, 2)
                          + pow((max(lon3) - min(lon3)) * 78000, 2)), 0) AS spread_m
          FROM c GROUP BY 1)
    """
    show(con, lines, "7a. Names by number of distinct coordinate clusters (~110 m grid)",
         clusters + "SELECT coord_clusters, count(*) AS station_names FROM s GROUP BY 1 ORDER BY 1")
    show(con, lines, "7b. Names whose coordinates move the most (possible relocations)",
         clusters + "SELECT * FROM s WHERE coord_clusters > 1 ORDER BY spread_m DESC LIMIT 15")

    show(con, lines,
         f"8. Station continuity: present = at least {MIN_EVENTS} events that year (1 = yes)",
         continuity_sql())

    con.execute(build_station_summary_sql(OUT_DIR / "station_summary.csv"))
    lines.append("\nWrote data/processed/station_summary.csv")

    gbfs_files = sorted(RAW_DIR.glob("gbfs/station_information_*.json"))
    lines.append("\n--- 9. Live GBFS stations versus historical names ---")
    if not gbfs_files:
        lines.append("no GBFS station_information file found")
    else:
        try:
            con.execute(f"""
                CREATE OR REPLACE TEMP VIEW live AS
                SELECT s.station_id, s.name, s.lat, s.lon, s.capacity
                FROM (SELECT unnest(data.stations) AS s
                      FROM read_json({literal(gbfs_files[-1].as_posix())}))""")
            show(con, lines, "9a. Match rate", """
                WITH n25 AS (SELECT DISTINCT lower(trim(station_name)) AS k
                             FROM events WHERE year(ts_local) = 2025),
                     nall AS (SELECT DISTINCT lower(trim(station_name)) AS k FROM events)
                SELECT count(*) AS live_stations,
                       sum(CAST(lower(trim(name)) IN (SELECT k FROM n25) AS INTEGER)) AS in_2025,
                       sum(CAST(lower(trim(name)) IN (SELECT k FROM nall) AS INTEGER))
                           AS in_any_year,
                       min(capacity) AS cap_min, median(capacity) AS cap_median,
                       max(capacity) AS cap_max
                FROM live""")
            show(con, lines, "9b. Live stations with no historical match (first 10)", """
                SELECT station_id, name, capacity FROM live
                WHERE lower(trim(name)) NOT IN
                      (SELECT DISTINCT lower(trim(station_name)) FROM events)
                LIMIT 10""")
        except duckdb.Error as error:
            lines.append(f"could not read the GBFS file: {error}")

    report = "\n".join(lines)
    print(report)
    (OUT_DIR / "trip_profile.txt").write_text(report, encoding="utf-8")
    print("\nSaved report to data/processed/trip_profile.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
