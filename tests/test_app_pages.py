"""Smoke test: the data pages render without errors in both languages (synthetic data)."""

from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from test_analysis import make_hourly  # noqa: E402

STATIONS_CSV = (
    "station_id,name,borough,lat,lon,capacity,volume_tier,station_type,"
    "events_2023,events_2024,events_2025,historical_names\n"
    "1,Alpha / Beta,Ville-Marie,45.50,-73.57,20,high,street,1,1,1,Alpha / Beta\n"
    "2,Gamma / Delta,Ville-Marie,45.51,-73.58,30,low,street,1,1,1,Gamma / Delta\n"
)


@pytest.fixture
def data_env(tmp_path, monkeypatch):
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    make_hourly().write_parquet(processed / "hourly_station.parquet")
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "selected_stations.csv").write_text(STATIONS_CSV, encoding="utf-8")
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BIXI_REFERENCE_DIR", str(reference))


def _page(view: str, language: str) -> None:
    import streamlit as st

    from bixi.app import views

    st.session_state["language"] = language
    getattr(views, view)()


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("view", ["render_trip_analysis", "render_station_map"])
def test_page_renders(data_env, view, language):
    app = AppTest.from_function(_page, args=(view, language), default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    assert app.title[0].value


def test_missing_data_shows_translated_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "nothing"))
    app = AppTest.from_function(_page, args=("render_trip_analysis", "fr"), default_timeout=30)
    app.run()
    assert not app.exception
    assert "introuvable" in app.error[0].value
