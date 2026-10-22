"""Data and methodology: sources, choices, assumptions, and how to reproduce every number."""

from __future__ import annotations

import streamlit as st

from bixi.app.state import get_translator
from bixi.i18n import Translator

SECTIONS = ("data", "stations", "cleaning", "features", "models", "serving", "rebalancing")
ASSUMPTIONS = 6

# Edges of the pipeline diagram; node labels come from methodology.node_<name>.
EDGES = (
    ("trips", "hourly"),
    ("stations", "hourly"),
    ("hourly", "features"),
    ("weather", "features"),
    ("events", "features"),
    ("features", "models"),
    ("models", "store"),
    ("store", "api"),
    ("api", "dashboard"),
    ("store", "rebalancing"),
    ("rebalancing", "dashboard"),
)
SOURCES = ("trips", "stations", "weather", "events")

REPRODUCE = """\
make install
python -m bixi.download all                 # trips, stations, observed weather
python -m bixi.download weather-forecast    # archived day-ahead forecasts
make data                                   # station selection, ingestion, features
python -m bixi.models                       # baselines, backtests, holdout, final models
python -m bixi.forecast export-holdout      # the forecast run served by the API
make rebalance                              # rebalancing scenarios
make app                                    # this dashboard (and: make api)
"""


def pipeline_dot(tr: Translator) -> str:
    """Graphviz source for the pipeline diagram, labelled in the active language."""
    nodes = {name for edge in EDGES for name in edge}
    lines = [
        "digraph pipeline {",
        '  rankdir=LR; bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=11,'
        ' color="#898781", fillcolor="#ffffff", fontcolor="#1f1f1f"];',
        '  edge [color="#898781"];',
    ]
    for name in sorted(nodes):
        label = tr.t(f"methodology.node_{name}").replace('"', "'").replace("\n", "\\n")
        fill = ', fillcolor="#dbe8f8"' if name in SOURCES else ""
        lines.append(f'  {name} [label="{label}"{fill}];')
    lines += [f"  {a} -> {b};" for a, b in EDGES]
    lines.append("}")
    return "\n".join(lines)


def render_methodology() -> None:
    tr = get_translator()
    st.title(tr.t("nav.methodology"))
    st.caption(tr.t("pages.methodology.description"))

    st.subheader(tr.t("methodology.pipeline_title"))
    st.graphviz_chart(pipeline_dot(tr))

    for section in SECTIONS:
        st.subheader(tr.t(f"methodology.{section}_title"))
        st.markdown(tr.t(f"methodology.{section}_body"))

    st.subheader(tr.t("methodology.assumptions_title"))
    st.markdown(
        "\n".join(f"{i}. {tr.t(f'methodology.assumption_{i}')}" for i in range(1, ASSUMPTIONS + 1))
    )

    st.subheader(tr.t("methodology.reproduce_title"))
    st.write(tr.t("methodology.reproduce_body"))
    st.code(REPRODUCE, language="bash")
