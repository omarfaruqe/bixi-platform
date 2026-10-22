"""Overview: the question, headline results, key findings and a way into every page.

Every number is read from the pipeline outputs, so the page stays in step with the results. A
missing result only removes the numbers that depend on it.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from bixi.analysis import headlines
from bixi.app.api_client import ApiUnavailable, get
from bixi.app.data import model_table, rebalancing_table, trip_headlines
from bixi.app.registry import PAGES
from bixi.app.state import get_translator, page_link
from bixi.i18n import Translator

COLUMNS = 3


def _service_badge(tr: Translator) -> None:
    try:
        run = get("/run")
    except ApiUnavailable as error:
        if error.no_active_run:
            label = tr.t("overview.service_no_run")
            st.badge(label, icon=":material/hourglass_empty:", color="orange")
        else:
            st.badge(tr.t("overview.service_offline"), icon=":material/cloud_off:", color="gray")
        return
    trained = tr.date(date.fromisoformat(run["trained_through"]), "long")
    st.badge(tr.t("overview.service_online", date=trained), icon=":material/check:", color="green")


def _kpis(tr: Translator, volume, forecast, rebalancing) -> None:
    """Up to four headline numbers, in equal columns so long French labels wrap in place."""
    cards = []
    if volume is not None:
        years = {"first": volume.first_year, "last": volume.last_year}
        help_text = tr.t("overview.kpi_trips_help", stations=volume.stations, **years)
        cards.append(
            dict(
                label=tr.t("overview.kpi_trips"), value=tr.number(volume.departures), help=help_text
            )
        )
    if forecast is not None:
        cards.append(
            dict(
                label=tr.t("overview.kpi_mae"),
                value=tr.number(forecast.mae, 2),
                # a positive skill shown as a green downward arrow: the error went down
                delta=tr.percent(forecast.skill_vs_naive, 0),
                delta_arrow="down",
                delta_color="normal",
                delta_description=tr.t("overview.vs_naive"),
                help=tr.t("overview.kpi_mae_help"),
            )
        )
        if forecast.coverage is not None:
            cards.append(
                dict(
                    label=tr.t("overview.kpi_coverage"),
                    value=tr.percent(forecast.coverage, 1),
                    help=tr.t("overview.kpi_coverage_help"),
                )
            )
    if rebalancing is not None:
        cards.append(
            dict(
                label=tr.t("overview.kpi_rebalancing"),
                value=tr.percent(rebalancing.reduction, 0),
                help=tr.t("overview.kpi_rebalancing_help", days=rebalancing.days),
            )
        )
    if cards:
        for column, card in zip(st.columns(len(cards)), cards, strict=True):
            column.metric(**card, border=True, height="stretch")


def _findings(tr: Translator, forecast, weather, rebalancing, commute) -> list[str]:
    found = []
    if forecast is not None:
        found.append(
            tr.t(
                "overview.finding_forecast",
                mae=tr.number(forecast.mae, 2),
                skill_naive=tr.percent(forecast.skill_vs_naive, 0),
                skill_best=tr.percent(forecast.skill_vs_best_baseline, 0),
            )
        )
    if weather is not None and weather > 0:
        found.append(tr.t("overview.finding_weather", gain=tr.percent(weather, 0)))
    if forecast is not None and forecast.coverage is not None:
        found.append(tr.t("overview.finding_intervals", coverage=tr.percent(forecast.coverage, 0)))
    if (
        rebalancing is not None
        and rebalancing.rule_reduction is not None
        and rebalancing.share_of_oracle is not None
        and rebalancing.km_saving_vs_rule is not None
    ):
        found.append(
            tr.t(
                "overview.finding_rebalancing",
                reduction=tr.percent(rebalancing.reduction, 0),
                rule=tr.percent(rebalancing.rule_reduction, 0),
                km=tr.percent(rebalancing.km_saving_vs_rule, 0),
                share=tr.percent(rebalancing.share_of_oracle, 0),
            )
        )
    if commute is not None:
        found.append(
            tr.t(
                "overview.finding_commute",
                window=f"{tr.hour(7)}–{tr.hour(10)}",
                station=commute.name,
                gain=tr.number(commute.gain),
                ratio=tr.number(commute.gain / commute.capacity, 1),
                capacity=commute.capacity,
            )
        )
    return found


def _explore(tr: Translator) -> None:
    st.subheader(tr.t("overview.explore_title"))
    specs = [spec for spec in PAGES if spec.key != "overview"]
    for start in range(0, len(specs), COLUMNS):
        for column, spec in zip(st.columns(COLUMNS), specs[start : start + COLUMNS], strict=False):
            with column.container(border=True, height="stretch"):
                page_link(spec.key, tr.t(f"nav.{spec.key}"), spec.icon)
                st.caption(tr.t(f"pages.{spec.key}.description"))


def render_overview() -> None:
    tr = get_translator()
    st.title(tr.t("app.title"))
    st.markdown(f"**{tr.t('app.question')}**")

    volume, commute = trip_headlines()
    overall = model_table("metrics_overall")
    forecast = headlines.forecast(overall)
    weather = headlines.weather_gain(overall)
    rebalancing = headlines.rebalancing(rebalancing_table("summary"))

    if volume is not None:
        st.write(
            tr.t(
                "overview.lead",
                stations=volume.stations,
                first=volume.first_year,
                last=volume.last_year,
            )
        )
    _service_badge(tr)
    _kpis(tr, volume, forecast, rebalancing)

    findings = _findings(tr, forecast, weather, rebalancing, commute)
    if findings:
        st.subheader(tr.t("overview.findings_title"))
        st.markdown("\n".join(f"- {line}" for line in findings))
    if None in (volume, forecast, rebalancing):
        st.caption(tr.t("overview.missing_results"))
    st.warning(f"**{tr.t('common.caveat')}** — {tr.t('methodology.assumption_1')}")

    _explore(tr)
