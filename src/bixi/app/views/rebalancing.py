"""Rebalancing simulation: scenario analysis of truck plans built from the forecasts."""

from __future__ import annotations

import polars as pl
import streamlit as st

from bixi.app.data import (
    rebalancing_assumptions,
    rebalancing_table,
    selected_stations,
)
from bixi.app.rebalancing_charts import (
    inventory_figure,
    problem_hours_figure,
    routes_map,
    sensitivity_figure,
    strategy_label,
)
from bixi.app.state import get_translator
from bixi.rebalancing.summary import scenario

KEY = "rb"
FILLS = (0.3, 0.5, 0.7)
TRUCKS = (1, 2, 4)
METHOD = "optimized_forecast"
DEFAULT_STATION = "107"  # fallback: Square-Victoria, the largest morning inflow


def _most_changed_station(inventory: pl.DataFrame) -> str | None:
    """The station whose bike count the plan changed most that day (a telling default)."""
    wide = inventory.filter(pl.col("strategy").is_in(["none", METHOD])).pivot(
        on="strategy", index=["station_id", "position"], values="inventory"
    )
    if wide.is_empty() or METHOD not in wide.columns or "none" not in wide.columns:
        return None
    ranked = (
        wide.group_by("station_id")
        .agg((pl.col(METHOD) - pl.col("none")).abs().sum().alias("change"))
        .sort("change", descending=True)
    )
    return ranked["station_id"][0]


def render_rebalancing() -> None:
    tr = get_translator()
    st.title(tr.t("nav.rebalancing"))
    st.caption(tr.t("pages.rebalancing.description"))

    summary = rebalancing_table("summary")
    assumptions = rebalancing_assumptions()
    if summary is None or assumptions is None:
        st.info(tr.t("rebalancing.not_run"))
        return

    st.warning(f"**{tr.t('common.caveat')}** — {tr.t('methodology.assumption_3')}")
    with st.expander(tr.t("rebalancing.assumptions_title")):
        windows = ", ".join(f"{tr.hour(s)}–{tr.hour(e)}" for s, e in assumptions["windows"])
        st.markdown(
            tr.t(
                "rebalancing.assumptions_body",
                capacity=assumptions["truck_capacity"],
                speed=tr.number(assumptions["speed_kmh"]),
                stop=tr.number(assumptions["stop_minutes"]),
                per_bike=tr.number(assumptions["minutes_per_bike"], 1),
                windows=windows,
                days=assumptions["days"],
            )
        )

    with st.container(horizontal=True, vertical_alignment="bottom"):
        fill = st.segmented_control(
            tr.t("rebalancing.start_fill"),
            FILLS,
            default=0.5,
            required=True,
            format_func=lambda f: tr.percent(f, 0),
            key=f"{KEY}_fill",
        )
        trucks = st.segmented_control(
            tr.t("rebalancing.trucks"),
            TRUCKS,
            default=2,
            required=True,
            key=f"{KEY}_trucks",
        )

    rows = scenario(summary, fill, trucks)
    by_strategy = {r["strategy"]: r for r in rows.iter_rows(named=True)}
    method = by_strategy.get(METHOD)
    if method is None:
        st.info(tr.t("common.no_data"))
        return
    with st.container(horizontal=True):
        st.metric(
            tr.t("rebalancing.kpi_reduction"),
            tr.percent(method["reduction"], 0),
            border=True,
            help=tr.t("rebalancing.kpi_reduction_help"),
        )
        share = method["share_of_oracle"]
        st.metric(
            tr.t("rebalancing.kpi_oracle"),
            tr.percent(share, 0) if share is not None else "—",
            border=True,
            help=tr.t("rebalancing.kpi_oracle_help"),
        )
        st.metric(tr.t("rebalancing.kpi_moved"), tr.number(method["bikes_moved"]), border=True)
        st.metric(tr.t("rebalancing.kpi_km"), tr.number(method["truck_km"]), border=True)

    st.subheader(tr.t("rebalancing.compare_title"))
    st.caption(tr.t("rebalancing.compare_caption"))
    st.plotly_chart(
        problem_hours_figure(rows, tr), key=f"{KEY}_compare", alt=tr.t("rebalancing.alt_compare")
    )

    st.subheader(tr.t("rebalancing.sensitivity_title"))
    st.caption(tr.t("rebalancing.sensitivity_caption"))
    st.plotly_chart(
        sensitivity_figure(summary.filter(pl.col("strategy") == METHOD), tr),
        key=f"{KEY}_sensitivity",
        alt=tr.t("rebalancing.alt_sensitivity"),
    )

    stops = rebalancing_table("stops")
    inventory = rebalancing_table("inventory")
    if stops is None or inventory is None:
        return
    st.subheader(tr.t("rebalancing.day_title"))
    st.caption(
        tr.t(
            "rebalancing.day_caption",
            fill=tr.percent(assumptions["start_fill"], 0),
            trucks=assumptions["trucks"],
        )
    )
    stations = selected_stations()
    dates = sorted(inventory["date"].unique().to_list())
    names = dict(stations.select("station_id", "name").iter_rows())
    capacity = dict(stations.select("station_id", "capacity").iter_rows())
    with st.container(horizontal=True, vertical_alignment="bottom"):
        day = st.selectbox(
            tr.t("forecasts.date"),
            dates,
            index=min(14, len(dates) - 1),
            format_func=lambda d: tr.date(d, "full"),
            key=f"{KEY}_date",
        )
        window = st.segmented_control(
            tr.t("rebalancing.window"),
            [w[0] for w in assumptions["windows"]],
            default=assumptions["windows"][0][0],
            required=True,
            format_func=lambda s: next(
                f"{tr.hour(a)}–{tr.hour(b)}" for a, b in assumptions["windows"] if a == s
            ),
            key=f"{KEY}_window",
        )
    day_stops = stops.filter(
        (pl.col("date") == day)
        & (pl.col("strategy") == METHOD)
        & (pl.col("window_start") == window)
    )
    if day_stops.is_empty():
        st.info(tr.t("rebalancing.no_moves"))
    else:
        st.pydeck_chart(
            routes_map(day_stops, stations, tr),
            height=480,
            key=f"{KEY}_map",
            alt=tr.t("rebalancing.alt_map"),
        )
        st.caption(tr.t("rebalancing.map_legend"))

    ids = sorted(names, key=names.get)
    default = _most_changed_station(inventory.filter(pl.col("date") == day)) or DEFAULT_STATION
    station = st.selectbox(
        tr.t("filters.station"),
        ids,
        index=ids.index(default) if default in ids else 0,
        format_func=names.get,
        key=f"{KEY}_station",
    )
    traj = inventory.filter((pl.col("date") == day) & (pl.col("station_id") == station))
    st.plotly_chart(
        inventory_figure(traj, int(capacity[station]), ("none", METHOD), tr),
        key=f"{KEY}_inventory",
        alt=tr.t("rebalancing.alt_inventory"),
    )
    st.caption(tr.t("rebalancing.inventory_caption", strategy=strategy_label(tr, METHOD)))
