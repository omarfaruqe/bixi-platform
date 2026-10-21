"""Hourly weather for Montréal from the Open-Meteo historical archive (ERA5 reanalysis).

Open-Meteo is free without an API key for non-commercial use; check its terms and attribute it
when you publish. The archive is *observed/analysed* weather, which is appropriate for
building historical features. It is NOT what a forecaster would have known the day before, so
Step 5 must decide how to respect the leakage rule in docs/decisions.md (for example by using
archived forecasts or lagged observations for the 24-hour horizon).

Timestamps are requested in UTC so they are unambiguous; convert to local time in Step 5 once
the timezone convention of the BIXI timestamps is confirmed.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from bixi.download import manifest
from bixi.download.http import DownloadError, fetch_json

LOGGER = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MONTREAL_LATITUDE = 45.5017
MONTREAL_LONGITUDE = -73.5673
ARCHIVE_LAG_DAYS = 7  # the archive trails real time by several days
HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "snow_depth",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
)


def request_params(year: int, today: date) -> dict[str, str] | None:
    """Query parameters for one calendar year, or None if the archive has nothing yet."""
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), today - timedelta(days=ARCHIVE_LAG_DAYS))
    if end < start:
        return None
    return {
        "latitude": str(MONTREAL_LATITUDE),
        "longitude": str(MONTREAL_LONGITUDE),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
    }


def download_weather(
    years: list[int] | tuple[int, ...],
    raw_dir: Path,
    *,
    force: bool = False,
    today: date | None = None,
) -> list[Path]:
    today = today or date.today()
    saved: list[Path] = []
    for year in years:
        params = request_params(year, today)
        if params is None:
            LOGGER.warning("%s: no archive data available yet; skipping", year)
            continue
        path = raw_dir / "weather" / f"open_meteo_archive_{year}.json"
        is_partial_year = params["end_date"] != f"{year}-12-31"
        if path.exists() and not force and not is_partial_year:
            LOGGER.info("%s: %s already downloaded (use --force to refetch)", year, path.name)
            saved.append(path)
            continue

        url = f"{ARCHIVE_URL}?{urlencode(params, safe=',')}"
        LOGGER.info("%s: fetching weather %s to %s", year, params["start_date"], params["end_date"])
        payload = fetch_json(url, timeout=120)
        if payload.get("error") or "hourly" not in payload:
            raise DownloadError(f"Open-Meteo error for {year}: {payload.get('reason', payload)}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        manifest.record(raw_dir, f"weather_{year}", url=url, path=str(path), timezone="UTC")
        saved.append(path)
    return saved


# --- Archived day-ahead forecasts (leakage-safe weather features, Step 5) -----------------------

PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
FORECAST_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "relative_humidity_2m",
    "cloud_cover",
    "wind_speed_10m",
)
DEFAULT_FORECAST_MODEL = "best_match"
SEASON_START = (4, 15)  # same window as the modelled season (bixi.ingest.rules)
SEASON_END = (11, 14)  # inclusive last date


def forecast_params(year: int, model: str) -> dict[str, str]:
    """Day-ahead forecasts (``*_previous_day1``) for one season, timestamps in UTC."""
    return {
        "latitude": str(MONTREAL_LATITUDE),
        "longitude": str(MONTREAL_LONGITUDE),
        "start_date": date(year, *SEASON_START).isoformat(),
        "end_date": date(year, *SEASON_END).isoformat(),
        "hourly": ",".join(f"{v}_previous_day1" for v in FORECAST_VARIABLES),
        "timezone": "UTC",
        "models": model,
    }


def forecast_coverage(payload: dict) -> dict[str, float]:
    """Share of non-missing hours per variable (Open-Meteo returns null where it has no data)."""
    hourly = payload.get("hourly", {})
    return {
        key.removesuffix("_previous_day1"): sum(v is not None for v in values) / max(len(values), 1)
        for key, values in hourly.items()
        if key != "time"
    }


def download_weather_forecasts(
    years: list[int] | tuple[int, ...],
    raw_dir: Path,
    *,
    model: str = DEFAULT_FORECAST_MODEL,
    force: bool = False,
) -> list[Path]:
    saved: list[Path] = []
    for year in years:
        path = raw_dir / "weather" / f"open_meteo_previous_runs_{model}_{year}.json"
        if path.exists() and not force:
            LOGGER.info("%s: %s already downloaded (use --force to refetch)", year, path.name)
            saved.append(path)
            continue
        params = forecast_params(year, model)
        url = f"{PREVIOUS_RUNS_URL}?{urlencode(params, safe=',')}"
        LOGGER.info("%s: fetching day-ahead forecasts (%s)", year, model)
        payload = fetch_json(url, timeout=120)
        if payload.get("error") or "hourly" not in payload:
            raise DownloadError(f"Open-Meteo error for {year}: {payload.get('reason', payload)}")
        coverage = forecast_coverage(payload)
        LOGGER.info(
            "%s: coverage %s",
            year,
            ", ".join(f"{name} {share:.0%}" for name, share in coverage.items()),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        manifest.record(
            raw_dir,
            f"weather_forecast_{model}_{year}",
            url=url,
            path=str(path),
            timezone="UTC",
            coverage={k: round(v, 3) for k, v in coverage.items()},
        )
        saved.append(path)
    return saved
