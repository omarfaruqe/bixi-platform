"""Streamlit entry point:  streamlit run src/bixi/app/main.py"""

from __future__ import annotations

import streamlit as st

from bixi.app.registry import PAGES
from bixi.app.state import (
    get_translator,
    init_language,
    register_pages,
    render_language_selector,
)
from bixi.app.views import (
    render_forecasts,
    render_methodology,
    render_model_performance,
    render_overview,
    render_rebalancing,
    render_station_map,
    render_trip_analysis,
)

init_language()
translator = get_translator()
st.set_page_config(page_title=translator.t("app.title"), page_icon="🚲", layout="wide")

RENDERERS = {
    "overview": render_overview,
    "trip_analysis": render_trip_analysis,
    "station_map": render_station_map,
    "forecasts": render_forecasts,
    "rebalancing": render_rebalancing,
    "model_performance": render_model_performance,
    "methodology": render_methodology,
}


def _build_pages() -> dict[str, st.Page]:
    tr = get_translator()
    return {
        spec.key: st.Page(
            RENDERERS[spec.key],
            title=tr.t(f"nav.{spec.key}"),
            icon=spec.icon,
            url_path=spec.key,
            default=spec.key == "overview",
        )
        for spec in PAGES
    }


pages = _build_pages()
register_pages(pages)
navigation = st.navigation(list(pages.values()))
render_language_selector()
st.sidebar.caption(translator.t("app.footer"))
navigation.run()
