from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from bixi.app.registry import PageSpec
from bixi.app.state import get_translator


def make_placeholder(spec: PageSpec) -> Callable[[], None]:
    def page() -> None:
        tr = get_translator()
        st.title(tr.t(f"nav.{spec.key}"))
        st.write(tr.t(f"pages.{spec.key}.description"))
        st.info(tr.t("pages.planned_step", step=spec.planned_step))

    page.__name__ = spec.key
    return page
