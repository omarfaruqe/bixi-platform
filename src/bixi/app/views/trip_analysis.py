"""Trip analysis: when and how much the study stations are used."""

from __future__ import annotations

import streamlit as st

from bixi.analysis.patterns import (
    apply_filters,
    daily_series,
    headline,
    hourly_profile,
    weekday_hour_matrix,
)
from bixi.app.charts import (
    daily_trend_figure,
    hourly_profile_figure,
    net_flow_figure,
    weekday_heatmap_figure,
)
from bixi.app.data import hourly_stations, selected_stations
from bixi.app.state import get_translator
from bixi.app.views.filters import day_type_filter, station_filter, years_filter

KEY = "trips"


def render_trip_analysis() -> None:
    tr = get_translator()
    st.title(tr.t("nav.trip_analysis"))
    st.caption(tr.t("pages.trip_analysis.description"))

    hourly = hourly_stations()
    stations = selected_stations()

    with st.container(horizontal=True, vertical_alignment="bottom"):
        station_ids = station_filter(tr, stations, KEY)
        years = years_filter(tr, KEY)
        day_types = day_type_filter(tr, KEY)

    if not years or not day_types:
        st.info(tr.t("common.no_data"))
        return
    df = apply_filters(hourly, station_ids, years, day_types)
    summary = headline(df)
    if summary is None:
        st.info(tr.t("common.no_data"))
        return

    with st.container(horizontal=True):
        st.metric(tr.t("analysis.kpi_departures"), tr.number(summary.total_departures), border=True)
        st.metric(
            tr.t("analysis.kpi_per_day"), tr.number(summary.mean_daily_departures), border=True
        )
        st.metric(tr.t("analysis.kpi_peak_hour"), tr.hour(summary.busiest_hour), border=True)
        st.metric(
            tr.t("analysis.kpi_weekend"),
            tr.percent(summary.weekend_ratio, 0) if summary.weekend_ratio else "—",
            help=tr.t("analysis.kpi_weekend_help"),
            border=True,
        )

    profile = hourly_profile(df)
    left, right = st.columns(2)
    with left:
        st.subheader(tr.t("analysis.profile_title"))
        st.caption(tr.t("analysis.profile_caption"))
        st.plotly_chart(
            hourly_profile_figure(profile, tr),
            key=f"{KEY}_profile",
            alt=tr.t("analysis.alt_profile"),
        )
    with right:
        st.subheader(tr.t("analysis.net_title"))
        st.caption(tr.t("analysis.net_caption"))
        st.plotly_chart(
            net_flow_figure(profile, tr), key=f"{KEY}_net", alt=tr.t("analysis.alt_net")
        )

    st.subheader(tr.t("analysis.heatmap_title"))
    st.caption(tr.t("analysis.heatmap_caption"))
    st.plotly_chart(
        weekday_heatmap_figure(weekday_hour_matrix(df), tr),
        key=f"{KEY}_heatmap",
        alt=tr.t("analysis.alt_heatmap"),
    )

    st.subheader(tr.t("analysis.trend_title"))
    st.caption(tr.t("analysis.trend_caption"))
    st.plotly_chart(
        daily_trend_figure(daily_series(df), tr), key=f"{KEY}_trend", alt=tr.t("analysis.alt_trend")
    )
