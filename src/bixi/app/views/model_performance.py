"""Model performance: baselines versus LightGBM, time-based backtests and error analysis."""

from __future__ import annotations

import polars as pl
import streamlit as st

from bixi.app.data import model_table, selected_stations
from bixi.app.model_charts import (
    coverage_figure,
    hourly_error_figure,
    importance_figure,
    model_label,
    model_mae_figure,
)
from bixi.app.state import get_translator
from bixi.features.build import TARGETS
from bixi.i18n import Translator
from bixi.models import summary

KEY = "perf"
SPLITS = ("holdout", "backtest")


def _ingredient_table(rows: pl.DataFrame, tr: Translator) -> pl.DataFrame:
    return pl.DataFrame(
        {
            tr.t("performance.col_model"): [model_label(tr, m) for m in rows["model"]],
            tr.t("performance.col_mae"): [tr.number(v, 3) for v in rows["mae"]],
            tr.t("performance.col_skill"): [tr.percent(v, 1) for v in rows["skill"]],
        }
    )


def _station_table(rows: pl.DataFrame, names: dict[str, str], tr: Translator) -> pl.DataFrame:
    return pl.DataFrame(
        {
            tr.t("map.col_station"): [names.get(s, s) for s in rows["station_id"]],
            tr.t("performance.col_mean_actual"): [tr.number(v, 1) for v in rows["mean_actual"]],
            tr.t("performance.col_mae"): [tr.number(v, 2) for v in rows["mae"]],
            tr.t("performance.col_relative"): [tr.percent(v, 0) for v in rows["relative_error"]],
        }
    )


def render_model_performance() -> None:
    tr = get_translator()
    st.title(tr.t("nav.model_performance"))
    st.caption(tr.t("pages.model_performance.description"))

    overall = model_table("metrics_overall")
    if overall is None:
        st.info(tr.t("performance.not_trained"))
        return

    with st.container(horizontal=True, vertical_alignment="bottom"):
        target = st.segmented_control(
            tr.t("performance.target"),
            TARGETS,
            default=TARGETS[0],
            required=True,
            format_func=lambda t: tr.t(f"charts.{t}"),
            key=f"{KEY}_target",
        )
        split = st.segmented_control(
            tr.t("performance.split"),
            SPLITS,
            default=SPLITS[0],
            required=True,
            format_func=lambda s: tr.t(f"performance.{s}"),
            key=f"{KEY}_split",
        )
    st.caption(tr.t(f"performance.{split}_help"))

    head = summary.headline(overall, split, target)
    if head is None:
        st.info(tr.t("common.no_data"))
        return
    with st.container(horizontal=True):
        st.metric(
            tr.t("performance.kpi_mae"),
            tr.number(head.mae, 2),
            border=True,
            help=tr.t("performance.kpi_mae_help"),
        )
        st.metric(
            tr.t("performance.kpi_skill_naive"),
            tr.percent(head.skill_vs_naive, 0),
            border=True,
            help=tr.t("performance.kpi_skill_naive_help"),
        )
        st.metric(
            tr.t("performance.kpi_skill_best"),
            tr.percent(head.skill_vs_best_baseline, 0),
            border=True,
            help=tr.t(
                "performance.kpi_skill_best_help", baseline=model_label(tr, head.best_baseline)
            ),
        )
        st.metric(
            tr.t("performance.kpi_coverage"),
            tr.percent(head.coverage, 0) if head.coverage is not None else "—",
            border=True,
            help=tr.t("performance.kpi_coverage_help"),
        )

    st.subheader(tr.t("performance.compare_title"))
    st.caption(tr.t("performance.compare_caption"))
    st.plotly_chart(
        model_mae_figure(summary.comparison(overall, split, target), tr),
        key=f"{KEY}_mae",
        alt=tr.t("performance.alt_compare"),
    )

    by_hour = model_table("errors_by_hour")
    if by_hour is not None and split == "holdout":
        rows = by_hour.filter(pl.col("target") == target)
        left, right = st.columns(2)
        with left:
            st.subheader(tr.t("performance.hourly_title"))
            st.caption(tr.t("performance.hourly_caption"))
            st.plotly_chart(
                hourly_error_figure(rows, tr),
                key=f"{KEY}_hourly",
                alt=tr.t("performance.alt_hourly"),
            )
        with right:
            st.subheader(tr.t("performance.coverage_title"))
            st.caption(tr.t("performance.coverage_caption"))
            st.plotly_chart(
                coverage_figure(rows, tr),
                key=f"{KEY}_coverage",
                alt=tr.t("performance.alt_coverage"),
            )

    st.subheader(tr.t("performance.ingredients_title"))
    st.caption(tr.t("performance.ingredients_caption"))
    st.dataframe(
        _ingredient_table(summary.ingredients(overall, split, target), tr),
        hide_index=True,
        alt=tr.t("performance.ingredients_title"),
    )

    importance = model_table("importance")
    if importance is not None and not importance.is_empty():
        st.subheader(tr.t("performance.importance_title"))
        st.caption(tr.t("performance.importance_caption"))
        st.plotly_chart(
            importance_figure(summary.importance_by_group(importance, target), tr),
            key=f"{KEY}_importance",
            alt=tr.t("performance.alt_importance"),
        )

    by_station = model_table("errors_by_station")
    if by_station is not None and split == "holdout":
        names = dict(selected_stations().select("station_id", "name").iter_rows())
        st.subheader(tr.t("performance.stations_title"))
        st.caption(tr.t("performance.stations_caption"))
        st.dataframe(
            _station_table(summary.hardest_stations(by_station, target), names, tr),
            hide_index=True,
            alt=tr.t("performance.stations_title"),
        )
