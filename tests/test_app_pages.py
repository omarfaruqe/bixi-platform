"""Smoke test: the data pages render without errors in both languages (synthetic data)."""

from __future__ import annotations

import polars as pl
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


def test_model_performance_page_renders(tmp_path, monkeypatch):
    results = tmp_path / "data" / "processed" / "model_results"
    results.mkdir(parents=True)
    rows = []
    for split in ("holdout", "backtest"):
        for target in ("departures", "arrivals"):
            for model, mae in (
                ("lgbm_poisson", 2.0),
                ("seasonal_naive", 3.0),
                ("same_hour_4w", 2.5),
                ("profile_mean", 2.6),
                ("lgbm_poisson_no_weather", 2.1),
            ):
                rows.append(
                    {
                        "split": split,
                        "target": target,
                        "model": model,
                        "mae": mae,
                        "mean_actual": 4.0,
                        "coverage": 0.8 if model == "lgbm_poisson" else None,
                    }
                )
    pl.DataFrame(rows).write_parquet(results / "metrics_overall.parquet")
    pl.DataFrame(
        [
            {"target": t, "model": m, "local_hour": h, "mae": 1.0 + h / 24, "coverage": 0.8}
            for t in ("departures", "arrivals")
            for m in ("lgbm_poisson", "seasonal_naive")
            for h in range(24)
        ]
    ).write_parquet(results / "errors_by_hour.parquet")
    pl.DataFrame(
        {
            "feature": ["departures_lag_24", "local_hour"],
            "gain_share": [0.8, 0.2],
            "target": "departures",
        }
    ).write_parquet(results / "importance.parquet")
    pl.DataFrame(
        {
            "target": "departures",
            "model": "lgbm_poisson",
            "station_id": ["1"],
            "mae": [1.0],
            "mean_actual": [2.0],
        }
    ).write_parquet(results / "errors_by_station.parquet")
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "selected_stations.csv").write_text(STATIONS_CSV, encoding="utf-8")
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BIXI_REFERENCE_DIR", str(reference))
    for language in ("en", "fr"):
        app = AppTest.from_function(
            _page, args=("render_model_performance", language), default_timeout=30
        )
        app.run()
        assert not app.exception, app.exception
        assert len(app.metric) == 4


def test_model_performance_without_results_shows_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "data"))
    app = AppTest.from_function(_page, args=("render_model_performance", "en"), default_timeout=30)
    app.run()
    assert not app.exception
    assert "python -m bixi.models" in app.info[0].value
