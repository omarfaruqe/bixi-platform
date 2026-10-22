"""Step 9: Overview headline numbers, the Overview and methodology pages, and the page registry."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from bixi.analysis import headlines
from bixi.analysis.patterns import prepare
from bixi.app.registry import PAGES
from bixi.i18n import Translator
from bixi.rebalancing.summary import summarize
from test_analysis import make_hourly
from test_app_pages import data_env  # noqa: F401  (pytest fixture)

STATIONS = pl.DataFrame(
    {"station_id": ["1", "2"], "name": ["Alpha / Beta", "Gamma / Delta"], "capacity": [20, 30]}
)


def overall_metrics() -> pl.DataFrame:
    rows = [
        ("lgbm_poisson", 2.0, 0.8),
        ("lgbm_poisson_no_weather", 2.5, None),
        ("seasonal_naive", 4.0, None),
        ("same_hour_4w", 3.2, None),
        ("profile_mean", 3.5, None),
    ]
    return pl.DataFrame(
        [
            {"split": split, "target": "departures", "model": m, "mae": mae, "coverage": cov}
            for split in ("holdout", "backtest")
            for m, mae, cov in rows
        ]
    )


def rebalancing_summary() -> pl.DataFrame:
    hours = {"none": 100, "rule_forecast": 90, "optimized_forecast": 80, "optimized_oracle": 70}
    km = {"none": 0.0, "rule_forecast": 50.0, "optimized_forecast": 40.0, "optimized_oracle": 40.0}
    return summarize(
        pl.DataFrame(
            [
                {
                    "date": date(2025, 10, d),
                    "start_fill": 0.5,
                    "trucks": 2,
                    "strategy": s,
                    "empty_hours": h // 2,
                    "full_hours": h - h // 2,
                    "problem_hours": h,
                    "missing_bikes": 0.0,
                    "missing_docks": 0.0,
                    "bikes_moved": 0 if s == "none" else 60,
                    "truck_km": km[s],
                    "unmet_target_bikes": 0,
                }
                for d in (1, 2)
                for s, h in hours.items()
            ]
        )
    )


def test_volume_and_commute_from_hourly_data():
    hourly = prepare(make_hourly())
    volume = headlines.volume(hourly)
    assert volume.stations == 2 and volume.first_year == volume.last_year == 2025
    assert volume.departures == hourly["departures"].sum()
    commute = headlines.commute(hourly, STATIONS)
    # station 2 gains one bike at 8 h every day; station 1 loses two
    assert commute.station_id == "2" and commute.name == "Gamma / Delta"
    assert commute.gain == pytest.approx(1.0) and commute.capacity == 30


def test_forecast_and_weather_headlines():
    overall = overall_metrics()
    forecast = headlines.forecast(overall)
    assert forecast.skill_vs_naive == pytest.approx(0.5)
    assert forecast.skill_vs_best_baseline == pytest.approx(1 - 2.0 / 3.2)
    assert headlines.weather_gain(overall) == pytest.approx(0.2)
    assert headlines.weather_gain(overall.filter(pl.col("model") != "lgbm_poisson")) is None


def test_rebalancing_headline():
    r = headlines.rebalancing(rebalancing_summary())
    assert r.days == 2 and r.reduction == pytest.approx(0.2)
    assert r.rule_reduction == pytest.approx(0.1)
    assert r.share_of_oracle == pytest.approx(2 / 3)
    assert r.km_saving_vs_rule == pytest.approx(0.2)
    assert headlines.rebalancing(rebalancing_summary(), trucks=4) is None


def test_missing_inputs_give_none():
    assert headlines.volume(None) is None and headlines.commute(None, STATIONS) is None
    assert headlines.forecast(None) is None and headlines.weather_gain(None) is None
    assert headlines.rebalancing(None) is None


def test_every_page_has_a_material_icon_and_translations():
    for language in ("en", "fr"):
        tr = Translator(language)
        for spec in PAGES:
            assert spec.icon.startswith(":material/")
            assert tr.t(f"nav.{spec.key}") != f"nav.{spec.key}"
            assert tr.t(f"pages.{spec.key}.description") != f"pages.{spec.key}.description"


def test_pipeline_diagram_is_translated():
    from bixi.app.views.methodology import pipeline_dot

    dot = pipeline_dot(Translator("fr"))
    assert dot.startswith("digraph") and "Entrepôt de prévisions" in dot
    assert "trips -> hourly" in dot


# --- pages (AppTest) ------------------------------------------------------------------------

st_testing = pytest.importorskip("streamlit.testing.v1")


def _page(view: str, language: str) -> None:
    import streamlit as st

    from bixi.app import views

    st.session_state["language"] = language
    getattr(views, view)()


@pytest.fixture
def results_env(data_env, tmp_path, monkeypatch):  # noqa: F811
    processed = tmp_path / "data" / "processed"
    (processed / "model_results").mkdir()
    overall_metrics().write_parquet(processed / "model_results" / "metrics_overall.parquet")
    (processed / "rebalancing").mkdir()
    rebalancing_summary().write_parquet(processed / "rebalancing" / "summary.parquet")

    import bixi.app.views.overview as view

    monkeypatch.setattr(view, "get", lambda path: {"trained_through": "2025-09-30"})


@pytest.mark.parametrize("language", ["en", "fr"])
def test_overview_shows_headlines(results_env, language):
    app = st_testing.AppTest.from_function(_page, args=("render_overview", language))
    app.run(timeout=30)
    assert not app.exception, app.exception
    assert len(app.metric) == 4
    assert app.metric[1].value == ("2.00" if language == "en" else "2,00")
    text = " ".join(m.value for m in app.markdown)
    assert "Gamma / Delta" in text  # the commute finding names the station
    assert len(app.warning) == 1  # the observed-is-not-demand caveat


def test_overview_without_any_results(tmp_path, monkeypatch):
    import bixi.app.views.overview as view
    from bixi.app.api_client import ApiUnavailable

    def down(*_args, **_kwargs):
        raise ApiUnavailable("down")

    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("BIXI_REFERENCE_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(view, "get", down)
    app = st_testing.AppTest.from_function(_page, args=("render_overview", "fr"))
    app.run(timeout=30)
    assert not app.exception, app.exception
    assert len(app.metric) == 0 and not app.error
    assert "manquent" in " ".join(c.value for c in app.caption)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_methodology_renders(language):
    app = st_testing.AppTest.from_function(_page, args=("render_methodology", language))
    app.run(timeout=30)
    assert not app.exception, app.exception
    assert len(app.subheader) == 10
    assert "python -m bixi.models" in app.code[0].value
