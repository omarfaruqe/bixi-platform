"""Page views. Each view renders with the translator for the active language."""

from bixi.app.views.methodology import render_methodology
from bixi.app.views.overview import render_overview
from bixi.app.views.placeholder import make_placeholder
from bixi.app.views.station_map import render_station_map
from bixi.app.views.trip_analysis import render_trip_analysis

__all__ = [
    "make_placeholder",
    "render_methodology",
    "render_overview",
    "render_station_map",
    "render_trip_analysis",
]
