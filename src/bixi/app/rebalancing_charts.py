"""Figures for the Rebalancing simulation page. Streamlit-free.

Empty and full station-hours are two kinds of failure, shown as two categories (slots 1 and 2:
blue = no bike for a departure, orange = no dock for an arrival). Starting-fill scenarios take
slots 1-3 in fixed order. On the map, pickups and drop-offs use the net-flow colours from the
station map: red where bikes are taken away, blue where bikes are added.
"""

from __future__ import annotations

import plotly.graph_objects as go
import polars as pl
import pydeck as pdk

from bixi.app.charts import (
    AQUA,
    BLUE,
    LINE_WIDTH,
    MUTED,
    ORANGE,
    RED,
    _hex_rgb,
    _hour_axis,
    _layout,
)
from bixi.i18n import Translator

FILL_COLOURS = (BLUE, ORANGE, AQUA)
TRUCK_COLOURS = ((42, 120, 214), (235, 104, 52), (27, 175, 122), (98, 80, 214))


def strategy_label(tr: Translator, strategy: str) -> str:
    return tr.t(f"strategies.{strategy}")


def problem_hours_figure(rows: pl.DataFrame, tr: Translator) -> go.Figure:
    """Problem hours per day by strategy, split into empty and full station-hours."""
    rows = rows.reverse()  # first strategy at the top
    labels = [strategy_label(tr, s) for s in rows["strategy"]]
    fig = go.Figure()
    for column, colour in (("empty_hours", BLUE), ("full_hours", ORANGE)):
        name = tr.t(f"rebalancing.{column}")
        values = rows[column].to_list()
        fig.add_bar(
            x=values,
            y=labels,
            orientation="h",
            name=name,
            marker={"color": colour, "line": {"color": "white", "width": 2}},
            customdata=[tr.number(v, 0) for v in values],
            hovertemplate=f"{name}: %{{customdata}}<extra>%{{y}}</extra>",
        )
    fig = _layout(fig, tr, "", tr.t("rebalancing.problem_axis"))
    fig.update_layout(
        barmode="stack", height=80 + 46 * len(labels), bargap=0.35, legend_traceorder="normal"
    )
    fig.update_yaxes(title=None, zeroline=False)
    fig.update_xaxes(showgrid=True)
    return fig


def sensitivity_figure(rows: pl.DataFrame, tr: Translator) -> go.Figure:
    """Reduction in problem hours (optimized plan) by number of trucks, one line per fill."""
    fig = go.Figure()
    fills = sorted(rows["start_fill"].unique().to_list())
    for fill, colour in zip(fills, FILL_COLOURS, strict=False):
        part = rows.filter(pl.col("start_fill") == fill).sort("trucks")
        name = tr.t("rebalancing.fill_series", fill=tr.percent(fill, 0))
        trucks = part["trucks"].to_list()
        values = part["reduction"].to_list()
        fig.add_scatter(
            x=trucks,
            y=values,
            name=name,
            mode="lines+markers",
            line={"color": colour, "width": LINE_WIDTH},
            marker={"size": 9, "line": {"color": "white", "width": 2}},
            customdata=[tr.percent(v, 1) for v in values],
            hovertemplate=f"{name}<br>%{{x}} → %{{customdata}}<extra></extra>",
        )
    fig = _layout(fig, tr, tr.t("rebalancing.reduction_axis"), tr.t("rebalancing.trucks"))
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_xaxes(tickvals=sorted(rows["trucks"].unique().to_list()), showgrid=False)
    return fig


def inventory_figure(
    rows: pl.DataFrame, capacity: int, strategies: tuple[str, ...], tr: Translator
) -> go.Figure:
    """One station's bikes through the day for each strategy, with its dock count."""
    fig = go.Figure()
    fig.add_hline(
        y=capacity,
        line={"color": MUTED, "width": 1, "dash": "dash"},
        annotation_text=tr.t("rebalancing.capacity_line", docks=capacity),
        annotation_position="top left",
        annotation_font_color=MUTED,
    )
    for strategy, colour, dash in zip(strategies, (MUTED, BLUE), ("dash", "solid"), strict=False):
        part = rows.filter(pl.col("strategy") == strategy).sort("position")
        name = strategy_label(tr, strategy)
        positions = part["position"].to_list()
        values = part["inventory"].to_list()
        hours = part["local_hour"].to_list()
        fig.add_scatter(
            x=positions,
            y=values,
            name=name,
            mode="lines",
            line={"color": colour, "width": LINE_WIDTH, "shape": "hv", "dash": dash},
            customdata=[
                [tr.hour(h % 24), tr.number(v, 0)] for h, v in zip(hours, values, strict=True)
            ],
            hovertemplate=f"{name}: %{{customdata[1]}}<extra>%{{customdata[0]}}</extra>",
        )
    fig = _layout(fig, tr, tr.t("rebalancing.bikes_axis"), tr.t("charts.hour_of_day"))
    _hour_axis(fig, tr)
    fig.update_xaxes(range=[-0.5, 24.5])
    fig.update_yaxes(range=[0, capacity * 1.15])
    fig.update_layout(hovermode="x unified")
    return fig


def routes_map(stops: pl.DataFrame, stations: pl.DataFrame, tr: Translator) -> pdk.Deck:
    """Truck routes for one window: depot -> stops in order -> depot; stops sized by bikes."""
    meta = {r["station_id"]: r for r in stations.iter_rows(named=True)}
    depot = [float(stations["lon"].mean()), float(stations["lat"].mean())]
    paths, points = [], []
    for truck in sorted(stops["truck"].unique().to_list()):
        part = stops.filter(pl.col("truck") == truck).sort("seq")
        coords = [depot]
        for s in part.iter_rows(named=True):
            m = meta[s["station_id"]]
            coords.append([m["lon"], m["lat"]])
            pickup = s["bikes"] > 0
            points.append(
                {
                    "lon": m["lon"],
                    "lat": m["lat"],
                    "radius": 40 + 12 * abs(s["bikes"]),
                    "colour": [*_hex_rgb(RED if pickup else BLUE), 220],
                    "label": (
                        f"{m['name']}<br/>"
                        + tr.t(
                            "rebalancing.tooltip_pickup"
                            if pickup
                            else "rebalancing.tooltip_dropoff",
                            bikes=abs(s["bikes"]),
                            truck=truck + 1,
                        )
                    ),
                }
            )
        coords.append(depot)
        colour = TRUCK_COLOURS[truck % len(TRUCK_COLOURS)]
        paths.append({"path": coords, "colour": [*colour, 200]})
    layers = [
        pdk.Layer(
            "ScatterplotLayer",
            data=stations.select("lat", "lon").to_dicts(),
            get_position=["lon", "lat"],
            get_radius=30,
            get_fill_color=[*_hex_rgb(MUTED), 110],
        ),
        pdk.Layer(
            "PathLayer",
            data=paths,
            get_path="path",
            get_color="colour",
            width_min_pixels=3,
            joint_rounded=True,
            cap_rounded=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=points,
            get_position=["lon", "lat"],
            get_radius="radius",
            get_fill_color="colour",
            get_line_color=[255, 255, 255, 255],
            line_width_min_pixels=1.5,
            stroked=True,
            pickable=True,
        ),
    ]
    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=depot[1], longitude=depot[0], zoom=12.6),
        tooltip={"html": "{label}"},
        map_style=None,
    )
