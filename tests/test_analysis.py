"""Calendar, trip-pattern aggregations and figure builders (synthetic data only)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from bixi.analysis.patterns import (
    apply_filters,
    daily_series,
    headline,
    hourly_profile,
    prepare,
    station_flows,
    weekday_hour_matrix,
)
from bixi.app import charts
from bixi.features.calendar import easter_sunday, quebec_holidays
from bixi.i18n import Translator
from bixi.ingest.hourly import season_hours


def test_easter_dates():
    assert easter_sunday(2023) == date(2023, 4, 9)
    assert easter_sunday(2024) == date(2024, 3, 31)
    assert easter_sunday(2025) == date(2025, 4, 20)


def test_quebec_holidays_2025():
    days = quebec_holidays(2025)
    assert days[date(2025, 5, 19)] == "National Patriots' Day"  # Monday before May 25
    assert date(2025, 6, 24) in days and date(2025, 7, 1) in days
    assert date(2025, 9, 1) in days  # Labour Day
    assert date(2025, 10, 13) in days  # Thanksgiving
    assert date(2025, 9, 30) not in days  # federal-only day, not a Québec holiday


def test_patriots_day_when_may_25_is_a_monday():
    assert date(2026, 5, 18) in quebec_holidays(2026)  # May 25, 2026 is a Monday


def make_hourly(station_ids=("1", "2"), year=2025) -> pl.DataFrame:
    """Station 1: 2 departures at 8 h, 1 arrival at 17 h. Station 2: 1 arrival at 8 h."""
    grid = pl.DataFrame({"station_id": list(station_ids)}).join(season_hours(year), how="cross")
    local = pl.col("ts_utc").dt.convert_time_zone("America/Toronto")
    hour = local.dt.hour()
    return grid.with_columns(
        ts_local=local,
        departures=pl.when((pl.col("station_id") == "1") & (hour == 8)).then(2).otherwise(0),
        arrivals=pl.when(
            ((pl.col("station_id") == "1") & (hour == 17))
            | ((pl.col("station_id") == "2") & (hour == 8))
        )
        .then(1)
        .otherwise(0),
    ).with_columns(pl.col("departures", "arrivals").cast(pl.UInt32))


@pytest.fixture(scope="module")
def hourly() -> pl.DataFrame:
    return prepare(make_hourly())


def test_prepare_adds_calendar_columns(hourly):
    assert {"local_hour", "weekday", "day_type", "year", "net_flow"} <= set(hourly.columns)
    assert set(hourly["day_type"].unique()) == {"weekday", "weekend", "holiday"}


def test_hourly_profile_sums_stations_then_averages_days(hourly):
    profile = hourly_profile(hourly)
    at_8 = profile.filter(pl.col("local_hour") == 8).row(0, named=True)
    assert at_8["departures"] == pytest.approx(2.0)
    assert at_8["arrivals"] == pytest.approx(1.0)
    assert at_8["net_flow"] == pytest.approx(-1.0)


def test_station_flows_by_window(hourly):
    morning = {r["station_id"]: r for r in station_flows(hourly, "morning_peak").to_dicts()}
    assert morning["1"]["net_flow"] == pytest.approx(-2.0)
    assert morning["2"]["net_flow"] == pytest.approx(1.0)
    evening = {r["station_id"]: r for r in station_flows(hourly, "evening_peak").to_dicts()}
    assert evening["1"]["net_flow"] == pytest.approx(1.0)


def test_filters_and_headline(hourly):
    only_one = apply_filters(hourly, ["1"], [2025], ["weekday"])
    summary = headline(only_one)
    assert summary is not None
    assert summary.busiest_hour == 8
    assert summary.mean_daily_departures == pytest.approx(2.0)
    assert headline(apply_filters(hourly, ["1"], [2023], None)) is None


def test_matrix_and_daily_series_shapes(hourly):
    assert weekday_hour_matrix(hourly).height == 7 * 24
    daily = daily_series(hourly)
    assert daily["season_day"].min() == 0
    assert daily["smoothed"].null_count() == 0


@pytest.mark.parametrize("language", ["en", "fr"])
def test_every_figure_builds_in_both_languages(hourly, language):
    tr = Translator(language)
    profile = hourly_profile(hourly)
    figures = [
        charts.hourly_profile_figure(profile, tr),
        charts.net_flow_figure(profile, tr),
        charts.weekday_heatmap_figure(weekday_hour_matrix(hourly), tr),
        charts.daily_trend_figure(daily_series(hourly), tr),
    ]
    for fig in figures:
        assert fig.layout.separators == (", " if language == "fr" else ".,")


def test_diverging_colour_poles_and_midpoint():
    assert charts.diverging_colour(0, 10)[:3] == list(charts._hex_rgb(charts.GREY_MID))
    assert charts.diverging_colour(10, 10)[:3] == list(charts._hex_rgb(charts.BLUE))
    assert charts.diverging_colour(-50, 10)[:3] == list(charts._hex_rgb(charts.RED))
