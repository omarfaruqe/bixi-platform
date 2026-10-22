"""Cached data loading for the dashboard.

Expensive reads happen once per process (``st.cache_data``); every filter is applied afterwards
on the cached frame, which is cheap (770k rows).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import streamlit as st

from bixi.analysis.patterns import prepare
from bixi.app.state import get_translator
from bixi.config import get_settings


def _require(path: Path) -> Path:
    if not path.exists():
        st.error(get_translator().t("errors.data_not_found", path=path.as_posix()))
        st.stop()
    return path


@st.cache_data(max_entries=1, show_spinner=False)
def _read_hourly(path: str, mtime: float) -> pl.DataFrame:  # mtime busts the cache on re-ingest
    return prepare(pl.read_parquet(path))


@st.cache_data(max_entries=2, show_spinner=False)
def _read_csv(path: str, mtime: float) -> pl.DataFrame:
    return pl.read_csv(path, schema_overrides={"station_id": pl.String})


def hourly_stations() -> pl.DataFrame:
    path = _require(get_settings().processed_dir / "hourly_station.parquet")
    return _read_hourly(str(path), path.stat().st_mtime)


def selected_stations() -> pl.DataFrame:
    path = _require(get_settings().reference_dir / "selected_stations.csv")
    return _read_csv(str(path), path.stat().st_mtime)


def network_stations() -> pl.DataFrame | None:
    """Every live station, used only as map context; optional."""
    path = get_settings().reference_dir / "network_stations.csv"
    return _read_csv(str(path), path.stat().st_mtime) if path.exists() else None


@st.cache_data(max_entries=8, show_spinner=False)
def _read_parquet(path: str, mtime: float) -> pl.DataFrame:
    return pl.read_parquet(path)


def model_table(name: str) -> pl.DataFrame | None:
    """A Step 6 result table (data/processed/model_results/<name>.parquet), or None if absent."""
    path = get_settings().processed_dir / "model_results" / f"{name}.parquet"
    return _read_parquet(str(path), path.stat().st_mtime) if path.exists() else None


def rebalancing_table(name: str) -> pl.DataFrame | None:
    """A Step 8 result table (data/processed/rebalancing/<name>.parquet), or None if absent."""
    path = get_settings().processed_dir / "rebalancing" / f"{name}.parquet"
    return _read_parquet(str(path), path.stat().st_mtime) if path.exists() else None


def rebalancing_assumptions() -> dict | None:
    import json

    path = get_settings().processed_dir / "rebalancing" / "assumptions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@st.cache_data(max_entries=1, show_spinner=False)
def _trip_headlines(
    hourly_path: str, hourly_mtime: float, stations_path: str, stations_mtime: float
):
    from bixi.analysis import headlines

    hourly = _read_hourly(hourly_path, hourly_mtime)
    stations = _read_csv(stations_path, stations_mtime)
    return headlines.volume(hourly), headlines.commute(hourly, stations)


def trip_headlines():
    """(Volume, Commute) for the Overview page; (None, None) when the trip tables are absent."""
    settings = get_settings()
    hourly = settings.processed_dir / "hourly_station.parquet"
    stations = settings.reference_dir / "selected_stations.csv"
    if not (hourly.exists() and stations.exists()):
        return None, None
    return _trip_headlines(
        str(hourly), hourly.stat().st_mtime, str(stations), stations.stat().st_mtime
    )
