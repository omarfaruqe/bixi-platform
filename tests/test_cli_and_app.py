"""Step 10: command-line round trip, the API client, the report writer and the full app."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import polars as pl
import pytest

from test_app_pages import data_env  # noqa: F401  (pytest fixture)

pytest.importorskip("sqlalchemy")


def test_forecast_cli_exports_publishes_lists_and_activates(tmp_path, monkeypatch, capsys):
    from bixi.forecast.__main__ import main
    from test_api import STATIONS, predictions

    results = tmp_path / "data" / "processed" / "model_results"
    results.mkdir(parents=True)
    predictions(datetime(2025, 10, 1, 4, tzinfo=UTC), 48).write_parquet(
        results / "predictions.parquet"
    )
    reference = tmp_path / "reference"
    reference.mkdir()
    STATIONS.write_csv(reference / "selected_stations.csv")
    monkeypatch.setenv("BIXI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BIXI_REFERENCE_DIR", str(reference))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")

    assert main(["export-holdout"]) == 0
    run_file = tmp_path / "data" / "processed" / "forecasts" / "holdout-2025.parquet"
    assert run_file.exists() and run_file.with_suffix(".json").exists()

    assert main(["publish", str(run_file)]) == 0
    assert "192 forecasts and activated" in capsys.readouterr().out  # 2 stations x 2 targets x 48 h

    assert main(["runs"]) == 0
    assert capsys.readouterr().out.startswith("* holdout-2025")

    assert main(["activate", "holdout-2025"]) == 0
    assert main(["activate", "nope"]) == 1
    assert "Published runs: holdout-2025" in capsys.readouterr().err


def test_api_client_maps_failures_to_api_unavailable(monkeypatch):
    from bixi.app import api_client

    def fake(status: int):
        def _get(url, params=None, timeout=None):
            return httpx.Response(status, json={"url": url, "params": params})

        return _get

    monkeypatch.setenv("BIXI_API_URL", "http://api.test/")
    monkeypatch.setattr(api_client.httpx, "get", fake(200))
    api_client.get.clear()
    body = api_client.get("/run", (("target", "departures"),))
    assert body == {"url": "http://api.test/run", "params": {"target": "departures"}}

    monkeypatch.setattr(api_client.httpx, "get", fake(404))
    api_client.get.clear()
    with pytest.raises(api_client.ApiUnavailable, match="404") as error:
        api_client.get("/forecasts/2020-01-01")
    assert error.value.status == 404 and not error.value.no_active_run

    monkeypatch.setattr(api_client.httpx, "get", fake(503))
    api_client.get.clear()
    with pytest.raises(api_client.ApiUnavailable) as error:
        api_client.get("/run")
    assert error.value.no_active_run

    def refused(*_args, **_kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(api_client.httpx, "get", refused)
    api_client.get.clear()
    with pytest.raises(api_client.ApiUnavailable, match="refused"):
        api_client.get("/run")


def test_rebalancing_report_is_written(tmp_path):
    from bixi.rebalancing.model import Assumptions
    from bixi.rebalancing.summary import write_report
    from test_headlines import rebalancing_summary

    summary = rebalancing_summary()
    text = write_report(summary, pl.DataFrame(), Assumptions(), 2, tmp_path / "report.md")
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == text
    assert "| optimized_forecast | 80 |" in text and "| 50% |" in text


def test_full_app_navigation_and_footer(data_env, monkeypatch):  # noqa: F811
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("BIXI_API_URL", "http://127.0.0.1:9")  # nothing listens: offline badge
    app = AppTest.from_file("../src/bixi/app/main.py", default_timeout=60)
    app.run()
    assert not app.exception, app.exception
    assert app.title[0].value == "BIXI Demand Forecasting and Rebalancing"
    assert any("Open-Meteo" in c.value for c in app.sidebar.caption)

    app.sidebar.radio[0].set_value("fr").run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Prévision de la demande et rééquilibrage BIXI"
    assert app.query_params["lang"] in ("fr", ["fr"])


def test_theme_assets_exist():
    """Every font and image the theme points at is shipped with the app (no external requests)."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["server"]["enableStaticServing"] is True
    static = root / "src" / "bixi" / "app" / "static"
    for face in config["theme"]["fontFaces"]:
        assert face["url"].startswith("app/static/")
        assert (static / face["url"].removeprefix("app/static/")).is_file(), face["url"]
    assert (static / "logo.svg").is_file()
    for scheme in ("light", "dark"):
        assert config["theme"][scheme]["primaryColor"].startswith("#")
