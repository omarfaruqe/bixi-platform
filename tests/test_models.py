"""Step 6 tests: metrics, baselines, fold integrity, a tiny LightGBM fit, page summaries."""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from bixi.models import summary
from bixi.models.baselines import predict_baseline
from bixi.models.metrics import poisson_deviance_expr, skill, summarize


def test_metrics_on_known_values():
    df = pl.DataFrame(
        {"y": [0.0, 2.0, 4.0], "yhat": [1.0, 2.0, 2.0], "lo": [0, 1, 3], "hi": [1, 3, 5]}
    )
    m = summarize(df).row(0, named=True)
    assert m["mae"] == pytest.approx(1.0)
    assert m["rmse"] == pytest.approx(math.sqrt(5 / 3))
    assert m["coverage"] == pytest.approx(1.0)
    assert m["interval_width"] == pytest.approx(5 / 3)
    # Poisson deviance: y=0 -> 2*mu; y=mu -> 0; y=4, mu=2 -> 2*(4 ln 2 - 2)
    dev = pl.DataFrame({"y": [0.0, 2.0, 4.0], "yhat": [1.0, 2.0, 2.0]}).select(
        poisson_deviance_expr()
    )
    assert dev.to_series().to_list() == pytest.approx([2.0, 0.0, 2 * (4 * math.log(2) - 2)])


def test_perfect_forecast_has_zero_deviance_and_skill_is_relative():
    df = pl.DataFrame({"y": [0.0, 3.0], "yhat": [0.0, 3.0]})
    assert summarize(df)["poisson_deviance"][0] == pytest.approx(0.0, abs=1e-6)
    assert skill(0.75, 1.0) == pytest.approx(0.25)


def _grid() -> pl.DataFrame:
    rows = []
    for day in range(1, 29):
        for hour in range(24):
            rows.append(
                {
                    "station_id": "1",
                    "local_date": date(2025, 6, day),
                    "local_hour": hour,
                    "day_type": "weekday",
                    "departures": float(hour),
                    "departures_lag_168": float(hour) + 1,
                    "departures_lag_24": float(hour) + 2,
                    "departures_same_hour_4w": None if day < 3 else float(hour),
                }
            )
    return pl.DataFrame(rows)


def test_baselines():
    df = _grid()
    train, test = (
        df.filter(pl.col("local_date") < date(2025, 6, 20)),
        df.filter(pl.col("local_date") >= date(2025, 6, 20)),
    )
    naive = predict_baseline("seasonal_naive", train, test, "departures")
    assert naive.to_list()[:3] == [1.0, 2.0, 3.0]
    profile = predict_baseline("profile_mean", train, test, "departures")
    assert profile.to_list()[:3] == [0.0, 1.0, 2.0]  # mean by station, hour and day type
    early = df.filter(pl.col("local_date") == date(2025, 6, 1))
    four_week = predict_baseline("same_hour_4w", train, early, "departures")
    assert four_week.to_list()[:2] == [2.0, 3.0]  # missing 4-week mean falls back to lag 24
    with pytest.raises(ValueError):
        predict_baseline("nope", train, test, "departures")


def test_folds_never_train_on_their_test_period():
    lgb = pytest.importorskip("lightgbm")  # noqa: F841  (backtest imports LightGBM)
    from bixi.models.backtest import FOLDS, VALID_DAYS, split

    days = pl.date_range(date(2024, 4, 15), date(2025, 11, 15), eager=True)
    df = pl.DataFrame({"local_date": days}).with_columns(year=pl.col("local_date").dt.year())
    for fold in FOLDS:
        train, valid, test = split(df, fold, 2024)
        assert train["local_date"].max() < valid["local_date"].min()
        assert valid["local_date"].max() < fold.cutoff == test["local_date"].min()
        assert valid.height == VALID_DAYS
        assert test["local_date"].max() < fold.end
    holdout = [f for f in FOLDS if f.split == "holdout"]
    assert len(holdout) == 1 and all(
        f.end <= holdout[0].cutoff for f in FOLDS if f is not holdout[0]
    )


def test_lightgbm_fit_predict_save_load(tmp_path):
    pytest.importorskip("lightgbm")
    from bixi.models import lgbm

    rng = __import__("numpy").random.default_rng(0)
    n = 2000
    hour = rng.integers(0, 24, n)
    df = pl.DataFrame(
        {
            "station_id": rng.choice(["1", "2"], n),
            "volume_tier": "high",
            "station_type": "street",
            "local_hour": hour,
            "y": rng.poisson(1 + (hour >= 7) * 4).astype(float),
        }
    )
    features = ["station_id", "local_hour"]
    model = lgbm.fit(df[:1500], df[1500:], "y", features, "poisson", max_rounds=50)
    pred = model.predict(df[1500:])
    assert (pred >= 0).all()
    assert (
        pred[df[1500:]["local_hour"].to_numpy() >= 7].mean()
        > pred[df[1500:]["local_hour"].to_numpy() < 7].mean()
    )
    model.save(tmp_path / "m.txt")
    loaded = lgbm.FittedModel.load(tmp_path / "m.txt")
    assert loaded.features == features
    assert loaded.predict(df[1500:]) == pytest.approx(pred)
    quantile = lgbm.fit(df[:1500], df[1500:], "y", features, "quantile", 0.9, max_rounds=50)
    assert quantile.objective == "quantile_0.9"


OVERALL = pl.DataFrame(
    {
        "split": ["holdout"] * 5,
        "target": ["departures"] * 5,
        "model": [
            "lgbm_poisson",
            "seasonal_naive",
            "same_hour_4w",
            "profile_mean",
            "lgbm_poisson_oracle",
        ],
        "mae": [2.0, 3.0, 2.5, 2.6, 1.9],
        "coverage": [0.79, None, None, None, None],
    }
)


def test_summary_headline_and_tables():
    head = summary.headline(OVERALL, "holdout", "departures")
    assert head.skill_vs_naive == pytest.approx(1 / 3)
    assert head.best_baseline == "same_hour_4w"
    assert head.skill_vs_best_baseline == pytest.approx(0.2)
    assert head.coverage == pytest.approx(0.79)
    assert summary.headline(OVERALL, "backtest", "departures") is None
    assert (
        "lgbm_poisson_oracle" not in summary.comparison(OVERALL, "holdout", "departures")["model"]
    )
    ingredients = summary.ingredients(OVERALL, "holdout", "departures")
    assert ingredients["model"].to_list() == ["lgbm_poisson", "lgbm_poisson_oracle"]


def test_importance_groups_and_hardest_stations():
    importance = pl.DataFrame(
        {
            "feature": ["departures_lag_24", "local_hour", "fc_precipitation", "x"],
            "gain_share": [0.6, 0.2, 0.15, 0.05],
            "target": "departures",
        }
    )
    groups = dict(summary.importance_by_group(importance, "departures").iter_rows())
    assert groups == pytest.approx(
        {"lags": 0.6, "calendar": 0.2, "weather_forecast": 0.15, "other": 0.05}
    )
    by_station = pl.DataFrame(
        {
            "target": "departures",
            "model": "lgbm_poisson",
            "station_id": ["a", "b"],
            "mae": [1.0, 2.0],
            "mean_actual": [0.5, 10.0],
        }
    )
    assert summary.hardest_stations(by_station, "departures")["station_id"].to_list() == ["a", "b"]


def test_conformal_margin_widens_narrow_intervals_and_narrows_wide_ones():
    import numpy as np

    from bixi.models.metrics import conformal_margin

    rng = np.random.default_rng(1)
    y = rng.normal(0, 1, 4000)
    calib, new = y[:2000], y[2000:]
    narrow = conformal_margin(calib, np.full(2000, -0.5), np.full(2000, 0.5), 0.8)
    assert narrow > 0
    covered = ((new >= -0.5 - narrow) & (new <= 0.5 + narrow)).mean()
    assert covered == pytest.approx(0.8, abs=0.03)
    wide = conformal_margin(calib, np.full(2000, -5.0), np.full(2000, 5.0), 0.8)
    assert wide < 0
    assert conformal_margin([], [], [], 0.8) == 0.0
