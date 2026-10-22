"""Demand forecasts: day-ahead hourly forecasts with 80% intervals, served by the forecast API."""

from __future__ import annotations

from datetime import date

import polars as pl
import streamlit as st

from bixi.app.api_client import ApiUnavailable, get
from bixi.app.model_charts import forecast_day_figure
from bixi.app.state import get_translator
from bixi.features.build import TARGETS
from bixi.i18n import Translator

KEY = "fc"
WINDOWS = ("all_day", "morning_peak", "evening_peak")
DEFAULT_STATION = "218"  # du Mont-Royal / Clark, the busiest study station


def _signed(tr: Translator, value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "—"
    return ("+" if value > 0 else "") + tr.number(value, decimals)


def _station_table(rows: list[dict], tr: Translator) -> pl.DataFrame:
    return pl.DataFrame(
        {
            tr.t("map.col_station"): [r["name"] for r in rows],
            tr.t("forecasts.col_forecast_net"): [_signed(tr, r["forecast_net"]) for r in rows],
            tr.t("forecasts.col_actual_net"): [_signed(tr, r["actual_net"]) for r in rows],
            tr.t("forecasts.col_forecast_dep"): [tr.number(r["forecast_departures"]) for r in rows],
            tr.t("forecasts.col_forecast_arr"): [tr.number(r["forecast_arrivals"]) for r in rows],
            tr.t("map.capacity"): [r["capacity"] for r in rows],
        }
    )


def render_forecasts() -> None:
    tr = get_translator()
    st.title(tr.t("nav.forecasts"))
    st.caption(tr.t("pages.forecasts.description"))

    try:
        run = get("/run")
        dates = [date.fromisoformat(d) for d in get("/forecasts/dates")["dates"]]
        stations = get("/stations")
    except ApiUnavailable as error:
        if error.no_active_run:
            st.info(tr.t("errors.no_forecast_run"))
        else:
            st.error(tr.t("errors.api_unavailable"))
        return
    if not dates:
        st.info(tr.t("common.no_data"))
        return

    if run["source"] == "holdout":
        st.info(
            tr.t(
                "forecasts.holdout_note",
                trained=tr.date(date.fromisoformat(run["trained_through"])),
                start=tr.date(dates[0]),
                end=tr.date(dates[-1]),
            )
        )

    names = {s["station_id"]: s["name"] for s in stations}
    station_ids = sorted(names, key=names.get)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        day = st.selectbox(
            tr.t("forecasts.date"),
            dates,
            index=min(14, len(dates) - 1),
            format_func=lambda d: tr.date(d, "full"),
            key=f"{KEY}_date",
        )
        station = st.selectbox(
            tr.t("filters.station"),
            station_ids,
            index=station_ids.index(DEFAULT_STATION) if DEFAULT_STATION in station_ids else 0,
            format_func=names.get,
            key=f"{KEY}_station",
        )
        target = st.segmented_control(
            tr.t("performance.target"),
            TARGETS,
            default=TARGETS[0],
            required=True,
            format_func=lambda t: tr.t(f"charts.{t}"),
            key=f"{KEY}_target",
        )

    try:
        points = get(
            f"/forecasts/{day.isoformat()}",
            (("station_id", station), ("target", target)),
        )["points"]
    except ApiUnavailable:
        st.error(tr.t("errors.api_unavailable"))
        return

    total_fc = sum(p["yhat"] for p in points)
    observed = [p for p in points if p["actual"] is not None]
    total_actual = sum(p["actual"] for p in observed) if observed else None
    inside = sum(1 for p in observed if p["lo"] <= p["actual"] <= p["hi"])
    with st.container(horizontal=True):
        st.metric(tr.t("forecasts.kpi_forecast"), tr.number(total_fc), border=True)
        st.metric(
            tr.t("forecasts.kpi_actual"),
            tr.number(total_actual) if total_actual is not None else "—",
            border=True,
        )
        st.metric(
            tr.t("forecasts.kpi_error"),
            tr.percent((total_fc - total_actual) / total_actual, 0) if total_actual else "—",
            border=True,
            help=tr.t("forecasts.kpi_error_help"),
        )
        st.metric(
            tr.t("forecasts.kpi_inside"),
            f"{inside} / {len(observed)}" if observed else "—",
            border=True,
            help=tr.t("forecasts.kpi_inside_help"),
        )

    st.subheader(tr.t("forecasts.chart_title", station=names[station]))
    st.caption(tr.t("forecasts.chart_caption"))
    st.plotly_chart(
        forecast_day_figure(points, tr), key=f"{KEY}_chart", alt=tr.t("forecasts.alt_chart")
    )

    st.subheader(tr.t("forecasts.stations_title"))
    st.caption(tr.t("forecasts.stations_caption"))
    window = st.segmented_control(
        tr.t("map.window"),
        WINDOWS,
        default="morning_peak",
        required=True,
        format_func=lambda w: tr.t(f"map.{w}"),
        key=f"{KEY}_window",
    )
    try:
        summary = get(f"/forecasts/{day.isoformat()}/stations", (("window", window),))
    except ApiUnavailable:
        st.error(tr.t("errors.api_unavailable"))
        return
    st.dataframe(
        _station_table(summary["stations"], tr),
        hide_index=True,
        alt=tr.t("forecasts.stations_title"),
    )
