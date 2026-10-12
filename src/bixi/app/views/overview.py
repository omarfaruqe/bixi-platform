from __future__ import annotations

from datetime import date

import streamlit as st

from bixi.app.registry import PAGES
from bixi.app.state import get_translator


def render_overview() -> None:
    tr = get_translator()
    st.title(tr.t("app.title"))
    st.subheader(tr.t("app.question"))
    st.warning(f"**{tr.t('common.caveat')}** — {tr.t('methodology.assumption_1')}")

    st.markdown("---")
    for spec in PAGES:
        if spec.key == "overview":
            continue
        st.markdown(
            f"**{spec.icon} {tr.t(f'nav.{spec.key}')}** — {tr.t(f'pages.{spec.key}.description')}"
        )

    # Quick visual check of locale-aware formatting (useful while developing).
    with st.expander(tr.t("app.locale_check")):
        st.write(tr.date(date.today()))
        st.write(tr.number(1234567.891, decimals=1))
        st.write(tr.percent(0.1234))
        st.caption(tr.t("app.station_names_note"))
