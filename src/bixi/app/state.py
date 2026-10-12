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
