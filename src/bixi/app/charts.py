"""Figure builders for the dashboard. Streamlit-free, so tests can build every figure.

Colour roles (validated reference palette, see docs/decisions.md section 10):
departures = blue, arrivals = orange, years = blue / orange / aqua in fixed order,
net flow = diverging blue (station gains bikes) <-> red (station loses bikes), grey midpoint,
magnitude = one-hue blue ramp. Every hover label is formatted by the translator.
"""

from __future__ import annotations

from datetime import date, timedelta

import plotly.graph_objects as go
import polars as pl
import pydeck as pdk

from bixi.i18n import Translator
from bixi.ingest.rules import SEASON_END, SEASON_START

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
RED = "#e34948"
GREY_MID = "#c3c2b7"
MUTED = "#898781"
YEAR_COLORS = (BLUE, ORANGE, AQUA)  # categorical slots 1-3, never cycled
SEQUENTIAL_BLUES = [
    [0.0, "#cde2fb"],
    [0.25, "#86b6ef"],
    [0.5, "#3987e5"],
    [0.75, "#1c5cab"],
    [1.0, "#0d366b"],
]
LINE_WIDTH = 2


def _separators(tr: Translator) -> str:
    """Plotly separators: decimal mark then thousands mark ('1,234.5' / '1 234,5')."""
    return ", " if tr.language == "fr" else ".,"


def _layout(fig: go.Figure, tr: Translator, y_title: str, x_title: str = "") -> go.Figure:
    fig.update_layout(
        separators=_separators(tr),
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        height=340,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0, "title": None},
        hoverlabel={"namelength": -1},
        bargap=0.25,
    )
    fig.update_yaxes(title=y_title, rangemode="tozero", zeroline=True)
    fig.update_xaxes(title=x_title or None, showgrid=False)
    return fig


def _hour_axis(fig: go.Figure, tr: Translator) -> None:
    ticks = list(range(0, 24, 3))
    fig.update_xaxes(tickvals=ticks, ticktext=[tr.hour(h) for h in ticks], range=[-0.5, 23.5])


def hourly_profile_figure(profile: pl.DataFrame, tr: Translator) -> go.Figure:
    """Average departures and arrivals per hour: the daily rhythm."""
    fig = go.Figure()
    hours = profile["local_hour"].to_list()
    for column, colour in (("departures", BLUE), ("arrivals", ORANGE)):
        name = tr.t(f"charts.{column}")
        values = profile[column].to_list()
        fig.add_scatter(
            x=hours,
            y=values,
            name=name,
            mode="lines",
            line={"color": colour, "width": LINE_WIDTH},
            customdata=[[tr.hour(h), tr.number(v, 1)] for h, v in zip(hours, values, strict=True)],
            hovertemplate=f"{name}: %{{customdata[1]}}<extra>%{{customdata[0]}}</extra>",
        )
    fig = _layout(fig, tr, tr.t("analysis.per_hour_axis"), tr.t("charts.hour_of_day"))
    _hour_axis(fig, tr)
    fig.update_layout(hovermode="x unified")
    return fig


def net_flow_figure(profile: pl.DataFrame, tr: Translator) -> go.Figure:
    """Arrivals minus departures per hour; above zero the selection gains bikes."""
    hours = profile["local_hour"].to_list()
    values = profile["net_flow"].to_list()
    fig = go.Figure(
        go.Bar(
            x=hours,
            y=values,
            marker={"color": [BLUE if v >= 0 else RED for v in values], "cornerradius": 4},
            customdata=[[tr.hour(h), tr.number(v, 1)] for h, v in zip(hours, values, strict=True)],
            hovertemplate="%{customdata[0]}: %{customdata[1]}<extra></extra>",
            name=tr.t("charts.net_flow"),
        )
    )
    fig = _layout(fig, tr, tr.t("analysis.net_axis"), tr.t("charts.hour_of_day"))
    fig.update_yaxes(rangemode="normal", zerolinecolor=MUTED, zerolinewidth=1)
    _hour_axis(fig, tr)
    fig.update_layout(showlegend=False)
    return fig


def weekday_heatmap_figure(matrix: pl.DataFrame, tr: Translator) -> go.Figure:
    """Mean departures by weekday (rows, Monday on top) and hour (columns)."""
    names = tr.weekday_names()
    grid = [[0.0] * 24 for _ in range(7)]
    for weekday, hour, value in matrix.select("weekday", "local_hour", "departures").iter_rows():
        grid[weekday][hour] = value
    text = [
        [f"{names[d]} {tr.hour(h)}: {tr.number(grid[d][h], 1)}" for h in range(24)]
        for d in range(7)
    ]
    fig = go.Figure(
        go.Heatmap(
            z=grid,
            x=list(range(24)),
            y=names,
            colorscale=SEQUENTIAL_BLUES,
            text=text,
            hovertemplate="%{text}<extra></extra>",
            xgap=2,
            ygap=2,
            colorbar={"title": {"text": tr.t("analysis.per_hour_axis"), "side": "right"}},
        )
    )
    fig = _layout(fig, tr, "", tr.t("charts.hour_of_day"))
    fig.update_yaxes(autorange="reversed", rangemode=None, zeroline=False, showgrid=False)
    _hour_axis(fig, tr)
    return fig


def _season_ticks(tr: Translator) -> tuple[list[int], list[str]]:
    """Month starts as days since April 15, labelled with localized month names."""
    months = tr.month_names()
    start = date(2025, *SEASON_START)
    ticks = [(date(2025, m, 1) - start).days for m in range(SEASON_START[0] + 1, SEASON_END[0] + 1)]
    labels = [months[m] for m in range(SEASON_START[0] + 1, SEASON_END[0] + 1)]
    return ticks, labels


def daily_trend_figure(daily: pl.DataFrame, tr: Translator) -> go.Figure:
    """Daily departures across the season, one line per year (7-day centred mean)."""
    fig = go.Figure()
    years = sorted(daily["year"].unique().to_list())
    all_years = sorted({2023, 2024, 2025} | set(years))
    for year in years:
        rows = daily.filter(pl.col("year") == year)
        colour = YEAR_COLORS[all_years.index(year) % len(YEAR_COLORS)]
        dates = rows["local_date"].to_list()
        smoothed = rows["smoothed"].to_list()
        raw = rows["departures"].to_list()
        fig.add_scatter(
            x=rows["season_day"].to_list(),
            y=smoothed,
            name=str(year),
            mode="lines",
            line={"color": colour, "width": LINE_WIDTH},
            customdata=[
                [tr.date(d, "medium"), tr.number(s, 0), tr.number(r, 0)]
                for d, s, r in zip(dates, smoothed, raw, strict=True)
            ],
            hovertemplate=(
                f"%{{customdata[0]}}<br>{tr.t('analysis.smoothed')}: %{{customdata[1]}}"
                f"<br>{tr.t('analysis.that_day')}: %{{customdata[2]}}<extra>{year}</extra>"
            ),
        )
    fig = _layout(fig, tr, tr.t("analysis.per_day_axis"))
    ticks, labels = _season_ticks(tr)
    last = (date(2025, *SEASON_END) - date(2025, *SEASON_START) - timedelta(days=1)).days
    fig.update_xaxes(tickvals=ticks, ticktext=labels, range=[0, last])
    return fig


# --- Map -----------------------------------------------------------------------------------


def _hex_rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _mix(a: str, b: str, t: float) -> list[int]:
    ra, rb = _hex_rgb(a), _hex_rgb(b)
    return [round(x + (y - x) * t) for x, y in zip(ra, rb, strict=True)]


def diverging_colour(value: float, max_abs: float) -> list[int]:
    """Grey at zero, blue for net arrivals, red for net departures (RGBA)."""
    t = min(abs(value) / max_abs, 1.0) if max_abs else 0.0
    return [*_mix(GREY_MID, BLUE if value >= 0 else RED, t), 230]


def station_map(flows: pl.DataFrame, network: pl.DataFrame | None, tr: Translator) -> pdk.Deck:
    """Study stations sized by volume and coloured by net flow; the network in grey behind."""
    # Colour scale capped at the 90th percentile: one extreme station (Square-Victoria gains
    # over 100 bikes on weekday mornings) would otherwise turn every other station grey.
    max_abs = float(flows["net_flow"].abs().quantile(0.9) or 1.0)
    max_total = float(flows["total"].max() or 1.0)
    records = [
        {
            "name": r["name"],
            "lat": r["lat"],
            "lon": r["lon"],
            "radius": 45 + 155 * (r["total"] / max_total) ** 0.5,
            "colour": diverging_colour(r["net_flow"], max_abs),
            "capacity": str(r["capacity"]),
            "departures": tr.number(r["departures"], 1),
            "arrivals": tr.number(r["arrivals"], 1),
            "net": ("+" if r["net_flow"] > 0 else "") + tr.number(r["net_flow"], 1),
        }
        for r in flows.iter_rows(named=True)
    ]
    layers = []
    if network is not None:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=network.select("lat", "lon").to_dicts(),
                get_position=["lon", "lat"],
                get_radius=22,
                get_fill_color=[*_hex_rgb(MUTED), 90],
                pickable=False,
            )
        )
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=records,
            get_position=["lon", "lat"],
            get_radius="radius",
            get_fill_color="colour",
            get_line_color=[255, 255, 255, 255],
            line_width_min_pixels=1.5,
            stroked=True,
            pickable=True,
        )
    )
    tooltip = {
        "html": (
            "<b>{name}</b><br/>"
            f"{tr.t('map.capacity')}: {{capacity}}<br/>"
            f"{tr.t('charts.departures')}: {{departures}}<br/>"
            f"{tr.t('charts.arrivals')}: {{arrivals}}<br/>"
            f"{tr.t('map.net')}: {{net}}"
        )
    }
    lat = float(flows["lat"].mean())
    lon = float(flows["lon"].mean())
    return pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=12.6),
        tooltip=tooltip,
        map_style=None,
    )
