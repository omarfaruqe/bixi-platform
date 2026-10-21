"""LightGBM models for hourly counts: mean forecasts and quantiles for 80% intervals.

Categorical columns (station, tier, type) are encoded with fixed category lists so the codes are
identical in training, backtests and serving. Hyperparameters are fixed and modest on purpose:
the comparison is between objectives, feature sets and baselines, not a tuning contest.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

CATEGORICAL = ("station_id", "volume_tier", "station_type")
BASE_PARAMS = {
    "learning_rate": 0.1,
    "max_bin": 127,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "max_cat_to_onehot": 4,
    "verbose": -1,
    "seed": 42,
    "deterministic": True,
    "force_row_wise": True,
}
OBJECTIVES = {
    "l2": {"objective": "regression", "metric": "l2"},
    "poisson": {"objective": "poisson", "metric": "poisson"},
    "tweedie": {"objective": "tweedie", "tweedie_variance_power": 1.2, "metric": "tweedie"},
}
MAX_ROUNDS = 2000
EARLY_STOPPING = 50


@dataclass
class Encoding:
    """Fixed category lists for the categorical features."""

    categories: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def fit(cls, df: pl.DataFrame) -> Encoding:
        return cls(
            {
                c: sorted(df[c].cast(pl.String).unique().drop_nulls().to_list())
                for c in CATEGORICAL
                if c in df.columns
            }
        )

    def matrix(self, df: pl.DataFrame, features: list[str]) -> np.ndarray:
        exprs = []
        for f in features:
            if f in self.categories:
                mapping = {v: i for i, v in enumerate(self.categories[f])}
                exprs.append(
                    pl.col(f)
                    .cast(pl.String)
                    .replace_strict(mapping, default=None, return_dtype=pl.Float64)
                    .alias(f)
                )
            else:
                exprs.append(pl.col(f).cast(pl.Float64).alias(f))
        return df.select(exprs).to_numpy()


@dataclass
class FittedModel:
    booster: lgb.Booster
    features: list[str]
    encoding: Encoding
    objective: str
    best_iteration: int

    def predict(self, df: pl.DataFrame) -> np.ndarray:
        pred = self.booster.predict(
            self.encoding.matrix(df, self.features), num_iteration=self.best_iteration
        )
        return np.clip(pred, 0.0, None)

    def importance(self) -> pl.DataFrame:
        gain = self.booster.feature_importance("gain", iteration=self.best_iteration)
        total = gain.sum() or 1.0
        return pl.DataFrame({"feature": self.features, "gain_share": gain / total}).sort(
            "gain_share", descending=True
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(path), num_iteration=self.best_iteration)
        meta = {
            "features": self.features,
            "categories": self.encoding.categories,
            "objective": self.objective,
            "best_iteration": self.best_iteration,
        }
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> FittedModel:
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        booster = lgb.Booster(model_file=str(path))
        return cls(
            booster,
            meta["features"],
            Encoding(meta["categories"]),
            meta["objective"],
            booster.current_iteration(),
        )


def _params(objective: str, alpha: float | None) -> dict:
    if objective == "quantile":
        return {**BASE_PARAMS, "objective": "quantile", "alpha": alpha, "metric": "quantile"}
    return {**BASE_PARAMS, **OBJECTIVES[objective]}


def fit(
    train: pl.DataFrame,
    valid: pl.DataFrame,
    target: str,
    features: list[str],
    objective: str = "poisson",
    alpha: float | None = None,
    encoding: Encoding | None = None,
    max_rounds: int = MAX_ROUNDS,
) -> FittedModel:
    """Train on ``train``, early-stop on ``valid`` (the most recent days before the cutoff)."""
    encoding = encoding or Encoding.fit(
        pl.concat([train.select(CATEGORICAL), valid.select(CATEGORICAL)])
    )
    cats = [f for f in features if f in encoding.categories]
    dtrain = lgb.Dataset(
        encoding.matrix(train, features),
        label=train[target].cast(pl.Float64).to_numpy(),
        feature_name=features,
        categorical_feature=cats,
        free_raw_data=True,
    )
    dvalid = lgb.Dataset(
        encoding.matrix(valid, features),
        label=valid[target].cast(pl.Float64).to_numpy(),
        reference=dtrain,
    )
    booster = lgb.train(
        _params(objective, alpha),
        dtrain,
        num_boost_round=max_rounds,
        valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(EARLY_STOPPING, verbose=False)],
    )
    name = objective if alpha is None else f"quantile_{alpha:g}"
    return FittedModel(booster, features, encoding, name, booster.best_iteration or max_rounds)


def describe(model: FittedModel) -> dict:
    return {
        "objective": model.objective,
        "best_iteration": model.best_iteration,
        **asdict(model.encoding),
    }
