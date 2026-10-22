"""Step 7 tests: forecast runs, the store and the API, on SQLite (production uses PostgreSQL)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
from fastapi.testclient import TestClient  # noqa: E402

from bixi.api.main import create_app  # noqa: E402
from bixi.forecast import publish, store  # noqa: E402

STATIONS = pl.DataFrame(
    {
        "station_id": ["1", "2"],
        "name": ["Alpha / Beta", "Gamma / Delta"],
        "borough": ["Ville-Marie", "Ville-Marie"],
        "lat": [45.50, 45.51],
        "lon": [-73.57, -73.58],
        "capacity": [20, 30],
        "volume_tier": ["high", "low"],
        "station_type": ["street", "street"],
    }
)


def predictions(start: datetime, hours: int) -> pl.DataFrame:
    """Holdout predictions in the Step 6 format: station 1 loses bikes at 8 h, station 2 gains."""
    rows = []
    for sid in ("1", "2"):
        for target in ("departures", "arrivals"):
            for i in range(hours):
                ts = start + timedelta(hours=i)
                local_hour = (ts - timedelta(hours=4)).hour
                busy = local_hour == 8
                gains = (sid == "1") == (target == "departures")
                y = 10.0 if busy and gains else 1.0
                rows.append(
                    {
                        "split": "holdout",
                        "model": "lgbm_poisson",
                        "station_id": sid,
                        "target": target,
                        "ts_utc": ts,
                        "y": y,
                        "yhat": y + 0.5,
                        "lo": y - 1.0,
                        "hi": y + 2.0,
                    }
                )
    rows.append({**rows[0], "model": "seasonal_naive"})  # other models are ignored
    return pl.DataFrame(rows).with_columns(
        pl.col("ts_utc").dt.replace_time_zone("UTC").dt.cast_time_unit("ms")
    )


@pytest.fixture
def engine(tmp_path):
    engine = store.engine_for(f"sqlite:///{tmp_path / 'forecasts.db'}")
    store.create_schema(engine)
    store.upsert_stations(engine, publish.station_rows(STATIONS))
    # 2025-10-31 04:00 UTC = local midnight; 4 days, including the DST change on 2025-11-02.
    run, df = publish.holdout_run(predictions(datetime(2025, 10, 31, 4, tzinfo=UTC), 4 * 24 + 1))
    store.publish_run(engine, run, publish.forecast_rows(df))
    return engine


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine))


def test_holdout_run_keeps_only_the_main_model():
    run, df = publish.holdout_run(predictions(datetime(2025, 10, 1, 4, tzinfo=UTC), 24))
    assert run.run_id == "holdout-2025" and run.trained_through == date(2025, 9, 30)
    assert df.height == 2 * 2 * 24
    assert df["local_date"].unique().to_list() == [date(2025, 10, 1)]
    with pytest.raises(ValueError):
        publish.holdout_run(pl.DataFrame({"split": ["backtest"], "model": ["x"]}))


def test_run_files_round_trip(tmp_path):
    run, df = publish.holdout_run(predictions(datetime(2025, 10, 1, 4, tzinfo=UTC), 24))
    path = tmp_path / "runs" / "r.parquet"
    publish.write_run(run, df, path)
    run2, df2 = publish.read_run(path)
    assert run2.run_id == run.run_id and run2.start_date == run.start_date
    assert df2.equals(df)
    assert json.loads(path.with_suffix(".json").read_text())["source"] == "holdout"


def test_model_runs_refuse_dates_inside_the_training_period(tmp_path):
    pytest.importorskip("lightgbm")
    (tmp_path / "manifest.json").write_text(
        json.dumps({"trained_through_local_date": "2025-11-14"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="out of sample"):
        publish.model_run(pl.DataFrame(), tmp_path, date(2025, 11, 1), date(2025, 11, 7))


def test_health_run_and_dates(client):
    assert client.get("/health").json() == {"status": "ok", "active_run": "holdout-2025"}
    run = client.get("/run").json()
    assert run["source"] == "holdout" and run["trained_through"] == "2025-09-30"
    dates = client.get("/forecasts/dates").json()["dates"]
    assert dates[0] == "2025-10-31" and "2025-11-02" in dates


def test_hourly_forecasts_and_dst_day(client):
    day = client.get("/forecasts/2025-10-31", params={"station_id": "1", "target": "departures"})
    points = day.json()["points"]
    assert len(points) == 24
    eight = next(p for p in points if p["local_hour"] == 8)
    assert eight["yhat"] == 10.5 and eight["lo"] == 9.0 and eight["actual"] == 10.0
    assert eight["local_time"].endswith("-04:00") and eight["ts_utc"].endswith("Z")
    fallback = client.get("/forecasts/2025-11-02", params={"station_id": "1", "target": "arrivals"})
    hours = [p["local_hour"] for p in fallback.json()["points"]]
    assert len(hours) == 25 and hours[:3] == [0, 1, 1]  # 1 am happens twice


def test_errors(client):
    assert client.get("/forecasts/2026-05-01").status_code == 404
    assert client.get("/forecasts/2025-10-31", params={"target": "rides"}).status_code == 422
    assert client.get("/forecasts/not-a-date").status_code == 422


def test_station_summary_is_sorted_by_forecast_net_change(client):
    body = client.get("/forecasts/2025-10-31/stations", params={"window": "morning_peak"}).json()
    rows = body["stations"]
    assert [r["station_id"] for r in rows] == ["1", "2"]
    first = rows[0]
    assert first["name"] == "Alpha / Beta" and first["capacity"] == 20
    assert first["forecast_departures"] == pytest.approx(10.5 + 1.5 + 1.5)  # 7, 8 and 9 h
    assert first["forecast_net"] == pytest.approx(
        first["forecast_arrivals"] - first["forecast_departures"]
    )
    assert first["actual_net"] == pytest.approx(3.0 - 12.0)


def test_no_active_run_is_a_503(tmp_path):
    engine = store.engine_for(f"sqlite:///{tmp_path / 'empty.db'}")
    store.create_schema(engine)
    client = TestClient(create_app(engine))
    assert client.get("/health").json()["active_run"] is None
    assert client.get("/run").status_code == 503


def test_activate_switches_runs_and_rejects_unknown_ids(engine):
    run, df = publish.holdout_run(predictions(datetime(2025, 10, 1, 4, tzinfo=UTC), 24))
    other = store.Run(**{**run.__dict__, "run_id": "second"})
    store.publish_run(engine, other, publish.forecast_rows(df))
    assert store.active_run(engine).run_id == "second"
    store.activate(engine, "holdout-2025")
    assert store.active_run(engine).run_id == "holdout-2025"
    with pytest.raises(KeyError):
        store.activate(engine, "missing")


def test_republishing_a_run_replaces_it(engine):
    """Regression: the second publish of a run hit the forecasts foreign key on PostgreSQL."""
    run, df = publish.holdout_run(predictions(datetime(2025, 10, 31, 4, tzinfo=UTC), 24))
    count = store.publish_run(engine, run, publish.forecast_rows(df))
    assert count == df.height
    assert [r["run_id"] for r in store.list_runs(engine)] == ["holdout-2025"]
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        stored = conn.execute(sa_count(store.forecasts)).scalar()
    assert stored == df.height


def sa_count(table):
    import sqlalchemy as sa

    return sa.select(sa.func.count()).select_from(table)
