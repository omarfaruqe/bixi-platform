"""Filter controls shared by the analysis pages, laid out in one row above the charts."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import streamlit as st

from bixi.features.calendar import DAY_TYPES
from bixi.i18n import Translator

YEARS = (2023, 2024, 2025)


def years_filter(tr: Translator, key: str) -> list[int]:
    return (
        st.pills(
            tr.t("filters.years"),
            YEARS,
            selection_mode="multi",
            default=list(YEARS),
            key=f"{key}_years",
        )
        or []
    )


def day_type_filter(tr: Translator, key: str, default: Sequence[str] = DAY_TYPES) -> list[str]:
    return (
        st.pills(
            tr.t("filters.day_type"),
            DAY_TYPES,
            selection_mode="multi",
            default=list(default),
            format_func=lambda d: tr.t(f"filters.{d}"),
            key=f"{key}_day_types",
        )
        or []
    )


def station_filter(tr: Translator, stations: pl.DataFrame, key: str) -> list[str] | None:
    """One station or all of them. Station names are shown untranslated."""
    ordered = stations.sort("name")
    names = dict(ordered.select("station_id", "name").iter_rows())
    choice = st.selectbox(
        tr.t("filters.station"),
        [None, *names],
        format_func=lambda sid: tr.t("filters.all_stations") if sid is None else names[sid],
        key=f"{key}_station",
    )
    return None if choice is None else [choice]
