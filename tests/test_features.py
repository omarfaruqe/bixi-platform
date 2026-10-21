"""Step 5 feature tests, including leakage guards. Synthetic data only."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from bixi.download.weather import forecast_coverage, forecast_params
from bixi.features.build import (
    FEATURE_GROUPS,
    add_lags,
    build_features,
    production_features,
)
from bixi.features.events import event_days, station_event_features
from bixi.features.weather import forecast_weather, observed_weather


def hours(start: datetime, n: int) -> list[datetime]:
    return [start + timedelta(hours=i) for i in range(n)]


def series(station: str, start: datetime, n: int) -> pl.DataFrame:
    """Departures = hour index, arrivals = 2 x hour index: every lag is easy to predict."""
    return pl.DataFrame(
        {
            "station_id": [station] * n,
            "ts_utc": hours(start, n),
            "departures": list(range(n)),
            "arrivals": [2 * i for i in range(n)],
        }
    ).with_columns(pl.col("ts_utc").dt.replace_time_zone("UTC").dt.cast_time_unit("ms"))


def test_lags_point_exactly_h_hours_back():
    df = add_lags(series("1", datetime(2025, 6, 1), 24 * 30)).sort("ts_utc")
    row = df.row(24 * 29, named=True)  # index 696
    assert row["departures_lag_24"] == 696 - 24
    assert row["departures_lag_168"] == 696 - 168
    assert row["arrivals_lag_48"] == 2 * (696 - 48)
    # sum of the 24 hours ending 24 h earlier: indices 649 ... 672
    assert row["departures_sum_24h_lag_24"] == sum(range(696 - 47, 696 - 23))
    # mean of the same hour 1-4 weeks back
    assert row["departures_same_hour_4w"] == pytest.approx(
        sum(696 - 168 * w for w in (1, 2, 3, 4)) / 4
    )


def test_no_lag_is_newer_than_24_hours():
    df = add_lags(series("1", datetime(2025, 6, 1), 24 * 10)).sort("ts_utc")
    first_day = df.head(24)
    lag_columns = [c for c in df.columns if "_lag_" in c or c.endswith("_4w")]
    assert all(first_day[c].null_count() == 24 for c in lag_columns)


def test_lags_do_not_cross_the_winter_gap():
    autumn = series("1", datetime(2024, 11, 14), 24)
    spring = series("1", datetime(2025, 4, 15), 48)
    df = add_lags(pl.concat([autumn, spring])).sort("ts_utc")
    assert (
        df.filter(pl.col("ts_utc").dt.year() == 2025).head(24)["departures_lag_24"].null_count()
        == 24
    )


def test_lags_stay_within_their_station():
    df = add_lags(
        pl.concat([series("1", datetime(2025, 6, 1), 48), series("2", datetime(2025, 6, 1), 48)])
    )
    lag = df.filter(pl.col("station_id") == "2").sort("ts_utc")["departures_lag_24"].to_list()
    assert lag[24:] == list(range(24))


def test_production_features_never_use_observed_weather_or_targets():
    features = production_features()
    assert not [f for f in features if f.startswith("obs_")]
    assert "departures" not in features and "arrivals" not in features
    assert set(FEATURE_GROUPS["weather_forecast"]) <= set(features)


def _weather_file(tmp_path, name: str, hourly: dict) -> list:
    path = tmp_path / name
    path.write_text(json.dumps({"utc_offset_seconds": 0, "hourly": hourly}), encoding="utf-8")
    return [path]


def test_weather_parsing_and_rain_flag(tmp_path):
    times = ["2025-06-01T00:00", "2025-06-01T01:00"]
    obs = observed_weather(
        _weather_file(
            tmp_path,
            "a.json",
            {
                "time": times,
                "temperature_2m": [20.0, 19.5],
                "apparent_temperature": [20.0, 19.0],
                "precipitation": [0.0, 1.2],
                "relative_humidity_2m": [50, 60],
                "cloud_cover": [10, 90],
                "wind_speed_10m": [5.0, 7.0],
            },
        )
    )
    assert obs["obs_is_rainy"].to_list() == [0, 1]
    assert obs["ts_utc"][0] == datetime(2025, 6, 1, tzinfo=UTC)

    fc = forecast_weather(
        _weather_file(
            tmp_path,
            "b.json",
            {
                "time": times,
                "temperature_2m_previous_day1": [21.0, None],
                "precipitation_previous_day1": [0.0, 0.5],
            },
        )
    )
    assert fc["fc_temperature_2m"].to_list() == [21.0, None]
    assert fc["fc_cloud_cover"].null_count() == 2  # not provided -> null column, not an error
    assert fc["fc_is_rainy"].to_list() == [0, 1]


def test_weather_file_must_be_utc(tmp_path):
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"utc_offset_seconds": -14400, "hourly": {"time": []}}))
    with pytest.raises(ValueError, match="UTC"):
        observed_weather([path])


EVENTS = pl.DataFrame(
    {
        "event": ["fest"],
        "start_date": [date(2025, 6, 1)],
        "end_date": [date(2025, 6, 3)],
        "venue": ["Place"],
        "lat": [45.5085],
        "lon": [-73.5664],
        "source": ["x"],
    }
)
STATIONS = pl.DataFrame(
    {
        "station_id": ["near", "far"],
        "lat": [45.5100, 45.5600],
        "lon": [-73.5664, -73.5664],
        "capacity": [20, 30],
        "volume_tier": ["high", "low"],
        "station_type": ["street", "transit"],
    }
)


def test_event_days_and_distances():
    assert event_days(EVENTS).height == 3  # inclusive date range
    feats = station_event_features(EVENTS, STATIONS)
    by_station = dict(
        feats.filter(pl.col("local_date") == date(2025, 6, 2))
        .select("station_id", "event_distance_km")
        .iter_rows()
    )
    assert by_station["near"] == pytest.approx(0.17, abs=0.01)
    assert by_station["far"] == pytest.approx(5.72, abs=0.05)


def test_build_features_end_to_end(tmp_path):
    start = datetime(2025, 6, 1, 4)  # midnight in Montréal
    hourly = pl.concat([series(s, start, 24 * 3) for s in ("near", "far")]).with_columns(
        ts_local=pl.col("ts_utc").dt.convert_time_zone("America/Toronto"),
        departures=pl.col("departures").cast(pl.UInt32),
        arrivals=pl.col("arrivals").cast(pl.UInt32),
    )
    system = hourly.group_by("ts_utc").agg(pl.col("departures").sum().alias("system_departures"))
    observed = pl.DataFrame({"ts_utc": hourly["ts_utc"].unique()}).with_columns(
        [pl.lit(1.0).alias(c) for c in FEATURE_GROUPS["weather_observed"]]
    )
    df = build_features(
        hourly=hourly,
        stations=STATIONS,
        system=system,
        observed=observed,
        forecast=None,
        events=station_event_features(EVENTS, STATIONS),
    )
    assert df.height == hourly.height
    assert set(production_features()) <= set(df.columns)
    assert df.filter(pl.col("local_date") == date(2025, 6, 4))["event_any"].sum() == 0
    assert df.filter(pl.col("local_date") == date(2025, 6, 2))["event_any"].min() == 1
    assert df["fc_temperature_2m"].null_count() == df.height  # no forecasts supplied


def test_forecast_download_parameters_and_coverage():
    params = forecast_params(2024, "gfs_seamless")
    assert params["start_date"] == "2024-04-15" and params["end_date"] == "2024-11-14"
    assert "precipitation_previous_day1" in params["hourly"].split(",")
    assert params["timezone"] == "UTC" and params["models"] == "gfs_seamless"
    coverage = forecast_coverage(
        {"hourly": {"time": [1, 2], "temperature_2m_previous_day1": [1.0, None]}}
    )
    assert coverage == {"temperature_2m": 0.5}
