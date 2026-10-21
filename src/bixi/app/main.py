"""Streamlit entry point:  streamlit run src/bixi/app/main.py"""

from __future__ import annotations

import streamlit as st

from bixi.app.registry import PAGES
from bixi.app.state import get_translator, init_language, render_language_selector
from bixi.app.views import (
    make_placeholder,
    render_methodology,
    render_overview,
    render_station_map,
    render_trip_analysis,
)

init_language()
translator = get_translator()
st.set_page_config(page_title=translator.t("app.title"), page_icon="🚲", layout="wide")

_CUSTOM_RENDERERS = {
    "overview": render_overview,
    "trip_analysis": render_trip_analysis,
    "station_map": render_station_map,
    "methodology": render_methodology,
}


def _build_pages() -> list[st.Page]:
    tr = get_translator()
    pages = []
    for spec in PAGES:
        render = _CUSTOM_RENDERERS.get(spec.key) or make_placeholder(spec)
        pages.append(
            st.Page(
                render,
                title=tr.t(f"nav.{spec.key}"),
                icon=spec.icon,
                url_path=spec.key,
                default=spec.key == "overview",
            )
        )
    return pages


navigation = st.navigation(_build_pages())
render_language_selector()
navigation.run()
