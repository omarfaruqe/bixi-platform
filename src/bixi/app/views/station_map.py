"""Station map: where bikes accumulate and where they run out."""

from __future__ import annotations

import polars as pl
import streamlit as st

from bixi.analysis.patterns import WINDOWS, apply_filters, station_flows
from bixi.app.charts import station_map
from bixi.app.data import hourly_stations, network_stations, selected_stations
from bixi.app.state import get_translator
from bixi.app.views.filters import day_type_filter, years_filter
from bixi.features.calendar import WEEKDAY
from bixi.i18n import Translator

KEY = "map"
TOP_N = 5


def _table(rows: pl.DataFrame, tr: Translator) -> pl.DataFrame:
    """Display table with locale-formatted numbers; station names untranslated."""
    return pl.DataFrame(
        {
            tr.t("map.col_station"): rows["name"],
            tr.t("map.col_net"): [
                ("+" if v > 0 else "") + tr.number(v, 1) for v in rows["net_flow"]
            ],
            tr.t("map.capacity"): rows["capacity"],
            tr.t("map.col_share"): [tr.percent(abs(v), 0) for v in rows["share_of_docks"]],
        }
    )


def render_station_map() -> None:
    tr = get_translator()
    st.title(tr.t("nav.station_map"))
    st.caption(tr.t("pages.station_map.description"))

    hourly = hourly_stations()
    stations = selected_stations()

    with st.container(horizontal=True, vertical_alignment="bottom"):
        window = st.segmented_control(
            tr.t("map.window"),
            list(WINDOWS),
            default="morning_peak",
            required=True,
            format_func=lambda w: tr.t(f"map.{w}"),
            key=f"{KEY}_window",
        )
        day_types = day_type_filter(tr, KEY, default=(WEEKDAY,))
        years = years_filter(tr, KEY)

    if not years or not day_types:
        st.info(tr.t("common.no_data"))
        return
    df = apply_filters(hourly, None, years, day_types)
    if df.is_empty():
        st.info(tr.t("common.no_data"))
        return

    flows = (
        station_flows(df, window or "all_day")
        .join(stations.select("station_id", "name", "lat", "lon", "capacity"), on="station_id")
        .with_columns(share_of_docks=pl.col("net_flow") / pl.col("capacity"))
        .sort("net_flow")
    )

    st.pydeck_chart(
        station_map(flows, network_stations(), tr),
        height=560,
        key=f"{KEY}_deck",
        alt=tr.t("map.alt"),
    )
    st.caption(tr.t("map.legend"))

    st.subheader(tr.t("map.losing_title"))
    st.dataframe(_table(flows.head(TOP_N), tr), hide_index=True, alt=tr.t("map.losing_title"))
    st.subheader(tr.t("map.gaining_title"))
    st.dataframe(
        _table(flows.reverse().head(TOP_N), tr), hide_index=True, alt=tr.t("map.gaining_title")
    )
    st.caption(tr.t("map.share_note"))
