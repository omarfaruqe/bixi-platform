"""Language state shared by every page. The selected language lives in session state
and in the ``?lang=`` query parameter so links are shareable."""

from __future__ import annotations

import streamlit as st

from bixi.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, Translator, normalize_language

LANGUAGE_KEY = "language"


def init_language() -> str:
    if LANGUAGE_KEY not in st.session_state:
        st.session_state[LANGUAGE_KEY] = normalize_language(st.query_params.get("lang"))
    return st.session_state[LANGUAGE_KEY]


def get_translator() -> Translator:
    return Translator(normalize_language(st.session_state.get(LANGUAGE_KEY)))


def render_language_selector() -> None:
    tr = get_translator()
    st.sidebar.radio(
        tr.t("app.language"),
        options=SUPPORTED_LANGUAGES,
        format_func=LANGUAGE_NAMES.__getitem__,
        key=LANGUAGE_KEY,
        horizontal=True,
    )
    st.query_params["lang"] = st.session_state[LANGUAGE_KEY]


PAGES_KEY = "_pages"


def register_pages(pages: dict) -> None:
    """Keep this run's page objects so views can link to each other with st.page_link."""
    st.session_state[PAGES_KEY] = pages


def page_link(key: str, label: str, icon: str | None = None) -> None:
    """A link to another page, or plain bold text when pages are not registered (tests)."""
    page = st.session_state.get(PAGES_KEY, {}).get(key)
    if page is None:
        st.markdown(f"**{label}**")
    else:
        st.page_link(page, label=f"**{label}**", icon=icon)
