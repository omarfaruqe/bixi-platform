"""Page views. Each view renders with the translator for the active language."""

from bixi.app.views.methodology import render_methodology
from bixi.app.views.overview import render_overview
from bixi.app.views.placeholder import make_placeholder

__all__ = ["make_placeholder", "render_methodology", "render_overview"]
