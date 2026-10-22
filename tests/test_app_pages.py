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


def _fake_api(path: str, params: tuple = ()):
    points = [
        {
            "station_id": "1",
            "target": "departures",
            "ts_utc": f"2025-10-15T{(h + 4) % 24:02d}:00:00Z",
            "local_time": f"2025-10-15T{h:02d}:00:00-04:00",
            "local_hour": h,
            "yhat": 5.0,
            "lo": 3.0,
            "hi": 8.0,
            "actual": 6.0 if h != 8 else 12.0,
        }
        for h in range(24)
    ]
    station_day = {
        "station_id": "1",
        "name": "Alpha / Beta",
        "capacity": 20,
        "forecast_departures": 30.0,
        "forecast_arrivals": 10.0,
        "forecast_net": -20.0,
        "actual_departures": 28.0,
        "actual_arrivals": 9.0,
        "actual_net": -19.0,
    }
    responses = {
        "/run": {"source": "holdout", "trained_through": "2025-09-30"},
        "/forecasts/dates": {"dates": ["2025-10-15", "2025-10-16"]},
        "/stations": [{"station_id": "1", "name": "Alpha / Beta"}],
        "/forecasts/2025-10-15": {"points": points},
        "/forecasts/2025-10-16": {"points": points},
        "/forecasts/2025-10-15/stations": {"stations": [station_day]},
        "/forecasts/2025-10-16/stations": {"stations": [station_day]},
    }
    return responses[path]


def test_forecasts_page_renders_from_the_api(monkeypatch):
    import bixi.app.views.forecasts as view

    monkeypatch.setattr(view, "get", _fake_api)
    for language in ("en", "fr"):
        app = AppTest.from_function(_page, args=("render_forecasts", language), default_timeout=30)
        app.run()
        assert not app.exception, app.exception
        assert len(app.metric) == 4
        assert app.metric[3].value == "23 / 24"  # the 8 h observation is outside [3, 8]


def test_forecasts_page_reports_an_unavailable_api(monkeypatch):
    import bixi.app.views.forecasts as view
    from bixi.app.api_client import ApiUnavailable

    def down(*_args, **_kwargs):
        raise ApiUnavailable("connection refused")

    monkeypatch.setattr(view, "get", down)
    app = AppTest.from_function(_page, args=("render_forecasts", "fr"), default_timeout=30)
    app.run()
    assert not app.exception
    assert "indisponible" in app.error[0].value


def test_rebalancing_page_renders(tmp_path, monkeypatch):
    import json
    from datetime import date

    from bixi.rebalancing.summary import summarize

    out = tmp_path / "data" / "processed" / "rebalancing"
    out.mkdir(parents=True)
    rows = []
    for fill in (0.3, 0.5, 0.7):
        for trucks in (1, 2, 4):
            for strategy, hours in (
                ("none", 100),
                ("rule_forecast", 90),
                ("optimized_forecast", 80),
                ("optimized_oracle", 75),
            ):
                rows.append(
                    {
                        "date": date(2025, 10, 15),
                        "start_fill": fill,
                        "trucks": trucks,
                        "strategy": strategy,
                        "empty_hours": hours // 2,
                        "full_hours": hours - hours // 2,
                        "problem_hours": hours,
                        "missing_bikes": 1.0,
                        "missing_docks": 1.0,
                        "bikes_moved": 0 if strategy == "none" else 50,
                        "truck_km": 0.0 if strategy == "none" else 40.0,
                        "unmet_target_bikes": 0,
                    }
                )
    summarize(pl.DataFrame(rows)).write_parquet(out / "summary.parquet")
    pl.DataFrame(
        {
            "date": [date(2025, 10, 15)] * 2,
            "strategy": ["optimized_forecast"] * 2,
            "window_start": [5, 5],
            "truck": [0, 0],
            "seq": [0, 1],
            "station_id": ["1", "2"],
            "bikes": [6, -6],
        }
    ).write_parquet(out / "stops.parquet")
    pl.DataFrame(
        [
            {
                "date": date(2025, 10, 15),
                "strategy": s,
                "station_id": sid,
                "position": h,
                "local_hour": h,
                "inventory": 5.0,
            }
            for s in ("none", "optimized_forecast")
            for sid in ("1", "2")
            for h in range(25)
        ]
    ).write_parquet(out / "inventory.parquet")
    (out / "assumptions.json").write_text(
        json.dumps(
            {
                "start_fill": 0.5,
                "trucks": 2,
                "truck_capacity": 20,
                "speed_kmh": 18.0,
                "stop_minutes": 4.0,
                "minutes_per_bike": 0.5,
                "windows": [[5, 7], [13, 15]],
                "days": 1,
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "selected_stations.csv").write_text(STATIONS_CSV, encoding="utf-8")
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BIXI_REFERENCE_DIR", str(reference))
    for language in ("en", "fr"):
        app = AppTest.from_function(
            _page, args=("render_rebalancing", language), default_timeout=30
        )
        app.run()
        assert not app.exception, app.exception
        assert len(app.metric) == 4
        assert app.metric[0].value.startswith("20")  # 100 -> 80 problem hours


def test_rebalancing_page_without_results_shows_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "data"))
    app = AppTest.from_function(_page, args=("render_rebalancing", "en"), default_timeout=30)
    app.run()
    assert not app.exception
    assert "python -m bixi.rebalancing" in app.info[0].value


def test_forecasts_page_without_a_published_run(monkeypatch):
    import bixi.app.views.forecasts as view
    from bixi.app.api_client import ApiUnavailable

    def no_run(*_args, **_kwargs):
        raise ApiUnavailable("503: no active forecast run", status=503)

    monkeypatch.setattr(view, "get", no_run)
    app = AppTest.from_function(_page, args=("render_forecasts", "en"), default_timeout=30)
    app.run()
    assert not app.exception and not app.error
    assert "python -m bixi.forecast publish" in app.info[0].value
