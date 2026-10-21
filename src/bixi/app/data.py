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
