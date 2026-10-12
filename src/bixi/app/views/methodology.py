from __future__ import annotations

import streamlit as st

from bixi.app.state import get_translator


def render_methodology() -> None:
    tr = get_translator()
    st.title(tr.t("nav.methodology"))
    st.write(tr.t("pages.methodology.description"))
    st.subheader(tr.t("methodology.assumptions_title"))
    for index in range(1, 5):
        st.markdown(f"{index}. {tr.t(f'methodology.assumption_{index}')}")
