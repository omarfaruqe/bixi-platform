"""Figures for the Model performance page. Streamlit-free, tested like charts.py.

Colour: the main model is blue and every comparison model a muted grey, so the eye goes to the
model that ships. Where three series appear (main model and two baselines) they take
categorical slots 1-3 in fixed order.
"""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl

from bixi.app.charts import AQUA, BLUE, GREY_MID, LINE_WIDTH, MUTED, ORANGE, _hour_axis, _layout
from bixi.i18n import Translator
from bixi.models.names import MAIN

HOURLY_MODELS = (MAIN, "seasonal_naive", "same_hour_4w")  # fixed colour order: blue, orange, aqua
HOURLY_COLOURS = (BLUE, ORANGE, AQUA)
TARGET_COVERAGE = 0.8


def model_label(tr: Translator, model: str) -> str:
    return tr.t(f"models.{model}")


def model_mae_figure(metrics: pl.DataFrame, tr: Translator) -> go.Figure:
    """Mean absolute error per model, best at the top."""
    rows = metrics.sort("mae", descending=True)
    labels = [model_label(tr, m) for m in rows["model"]]
    values = rows["mae"].to_list()
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={
                "color": [BLUE if m == MAIN else GREY_MID for m in rows["model"]],
                "cornerradius": 4,
            },
            text=[tr.number(v, 2) for v in values],
            textposition="outside",
            cliponaxis=False,
            customdata=[[lbl, tr.number(v, 3)] for lbl, v in zip(labels, values, strict=True)],
            hovertemplate="%{customdata[0]}: %{customdata[1]}<extra></extra>",
        )
    )
    fig = _layout(fig, tr, "", tr.t("performance.mae_axis"))
    fig.update_layout(height=60 + 34 * len(labels), showlegend=False, margin={"l": 8, "r": 48})
    fig.update_yaxes(title=None, zeroline=False)
    fig.update_xaxes(showgrid=True, rangemode="tozero")
    return fig


def hourly_error_figure(by_hour: pl.DataFrame, tr: Translator) -> go.Figure:
    """MAE by local hour for the main model and two baselines."""
    fig = go.Figure()
    for model, colour in zip(HOURLY_MODELS, HOURLY_COLOURS, strict=True):
        rows = by_hour.filter(pl.col("model") == model).sort("local_hour")
        if rows.is_empty():
            continue
        name = model_label(tr, model)
        hours = rows["local_hour"].to_list()
        values = rows["mae"].to_list()
        fig.add_scatter(
            x=hours,
            y=values,
            name=name,
            mode="lines",
            line={"color": colour, "width": LINE_WIDTH},
            customdata=[[tr.hour(h), tr.number(v, 2)] for h, v in zip(hours, values, strict=True)],
            hovertemplate=f"{name}: %{{customdata[1]}}<extra>%{{customdata[0]}}</extra>",
        )
    fig = _layout(fig, tr, tr.t("performance.col_mae"), tr.t("charts.hour_of_day"))
    _hour_axis(fig, tr)
    fig.update_layout(hovermode="x unified")
    return fig


def coverage_figure(by_hour: pl.DataFrame, tr: Translator) -> go.Figure:
    """Share of actual counts inside the 80% interval, by hour, against the 80% target."""
    rows = by_hour.filter(pl.col("model") == MAIN).sort("local_hour")
    hours = rows["local_hour"].to_list()
    values = rows["coverage"].to_list()
    fig = go.Figure()
    fig.add_hline(
        y=TARGET_COVERAGE,
        line={"color": MUTED, "width": 1, "dash": "dash"},
        annotation_text=tr.t("performance.coverage_target"),
        annotation_position="bottom right",
        annotation_font_color=MUTED,
    )
    fig.add_scatter(
        x=hours,
        y=values,
        name=tr.t("performance.coverage"),
        mode="lines+markers",
        line={"color": BLUE, "width": LINE_WIDTH},
        marker={"size": 8, "line": {"color": "white", "width": 2}},
        customdata=[[tr.hour(h), tr.percent(v, 0)] for h, v in zip(hours, values, strict=True)],
        hovertemplate="%{customdata[0]}: %{customdata[1]}<extra></extra>",
    )
    fig = _layout(fig, tr, tr.t("performance.coverage"), tr.t("charts.hour_of_day"))
    fig.update_yaxes(tickformat=".0%", range=[0.5, 1.0], rangemode=None)
    _hour_axis(fig, tr)
    fig.update_layout(showlegend=False)
    return fig


def importance_figure(groups: pl.DataFrame, tr: Translator) -> go.Figure:
    """Share of the model's total gain by feature group."""
    rows = groups.sort("gain_share")
    labels = [tr.t(f"feature_groups.{g}") for g in rows["group"]]
    values = rows["gain_share"].to_list()
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker={"color": BLUE, "cornerradius": 4},
            text=[tr.percent(v, 0) for v in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{text}<extra></extra>",
        )
    )
    fig = _layout(fig, tr, "", tr.t("performance.importance_axis"))
    fig.update_layout(height=60 + 40 * len(labels), showlegend=False, margin={"l": 8, "r": 48})
    fig.update_xaxes(tickformat=".0%", showgrid=True)
    fig.update_yaxes(title=None, zeroline=False)
    return fig
