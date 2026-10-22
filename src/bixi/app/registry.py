"""Page registry. Streamlit-free so tests can import it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    key: str  # used for URL path and translation keys: nav.<key>, pages.<key>.description
    icon: str  # Material Symbols name, shown in the sidebar and on the Overview page


PAGES: tuple[PageSpec, ...] = (
    PageSpec("overview", ":material/home:"),
    PageSpec("trip_analysis", ":material/bar_chart:"),
    PageSpec("station_map", ":material/map:"),
    PageSpec("forecasts", ":material/show_chart:"),
    PageSpec("rebalancing", ":material/local_shipping:"),
    PageSpec("model_performance", ":material/query_stats:"),
    PageSpec("methodology", ":material/menu_book:"),
)
