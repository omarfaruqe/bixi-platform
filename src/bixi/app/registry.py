"""Page registry. Streamlit-free so tests can import it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageSpec:
    key: str  # used for URL path and translation keys: nav.<key>, pages.<key>.description
    icon: str
    planned_step: int  # build step in which the page gets its real content


PAGES: tuple[PageSpec, ...] = (
    PageSpec("overview", "🏠", 9),
    PageSpec("trip_analysis", "📊", 4),
    PageSpec("station_map", "🗺️", 4),
    PageSpec("forecasts", "🔮", 7),
    PageSpec("rebalancing", "🚚", 8),
    PageSpec("model_performance", "🎯", 6),
    PageSpec("methodology", "📚", 10),
)
