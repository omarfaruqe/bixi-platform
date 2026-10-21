"""Read-only forecast API.

Run locally:   uvicorn bixi.api.main:app --reload        (needs DATABASE_URL)
Docs:          /docs (Swagger UI) and /openapi.json

All times are returned twice: ``ts_utc`` (unambiguous) and ``local_time`` (America/Toronto, with
its UTC offset), because a local hour repeats on the autumn DST change.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.engine import Engine

from bixi.config import get_settings
from bixi.forecast import store

LOCAL = ZoneInfo("America/Toronto")
WINDOWS = {"all_day": (0, 24), "morning_peak": (7, 10), "evening_peak": (16, 19)}


class Target(StrEnum):
    departures = "departures"
    arrivals = "arrivals"


class Window(StrEnum):
    all_day = "all_day"
    morning_peak = "morning_peak"
    evening_peak = "evening_peak"


class Health(BaseModel):
    status: str
    active_run: str | None


class Station(BaseModel):
    station_id: str
    name: str = Field(description="Original station name (never translated)")
    borough: str | None
    lat: float
    lon: float
    capacity: int = Field(description="Number of docks")
    volume_tier: str | None
    station_type: str | None


class RunInfo(BaseModel):
    run_id: str
    created_at: datetime
    source: str = Field(description="'holdout' (backtest forecasts) or 'model' (final models)")
    model_variant: str
    trained_through: date | None = Field(description="Last local date the model saw in training")
    start_date: date
    end_date: date
    details: dict


class Dates(BaseModel):
    run_id: str
    dates: list[date]


class Point(BaseModel):
    station_id: str
    target: Target
    ts_utc: datetime
    local_time: datetime
    local_hour: int
    yhat: float = Field(description="Forecast count for the hour")
    lo: float | None = Field(description="Lower bound of the 80% prediction interval")
    hi: float | None = Field(description="Upper bound of the 80% prediction interval")
    actual: float | None = Field(description="Observed count, when known")


class ForecastDay(BaseModel):
    run_id: str
    date: date
    points: list[Point]


class StationDay(BaseModel):
    station_id: str
    name: str
    capacity: int
    forecast_departures: float
    forecast_arrivals: float
    forecast_net: float = Field(description="Forecast arrivals minus departures (bikes gained)")
    actual_departures: float | None
    actual_arrivals: float | None
    actual_net: float | None


class StationsDay(BaseModel):
    run_id: str
    date: date
    window: Window
    stations: list[StationDay]


def get_engine(request: Request) -> Engine:
    """The app's engine; created from DATABASE_URL on first use unless injected (tests)."""
    if request.app.state.engine is None:
        request.app.state.engine = store.engine_for(get_settings().database_url)
    return request.app.state.engine


EngineDep = Annotated[Engine, Depends(get_engine)]


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(
        title="BIXI demand forecasts",
        version="1.0",
        description=(
            "Hourly departure and arrival forecasts with 80% prediction intervals for 50 BIXI "
            "stations in Montréal. Read-only."
        ),
        root_path=os.getenv("BIXI_API_ROOT_PATH", ""),
    )
    app.state.engine = engine

    def active(engine: Engine) -> store.Run:
        run = store.active_run(engine)
        if run is None:
            raise HTTPException(503, "No forecast run has been published yet")
        return run

    def in_run(run: store.Run, day: date) -> None:
        if not run.start_date <= day <= run.end_date:
            raise HTTPException(
                404, f"No forecasts for {day}; this run covers {run.start_date} to {run.end_date}"
            )

    @app.get("/health", response_model=Health, tags=["service"])
    def health(engine: EngineDep) -> Health:
        run = store.active_run(engine)
        return Health(status="ok", active_run=run.run_id if run else None)

    @app.get("/stations", response_model=list[Station], tags=["stations"])
    def stations(engine: EngineDep) -> list[dict]:
        return store.all_stations(engine)

    @app.get("/run", response_model=RunInfo, tags=["forecasts"])
    def run_info(engine: EngineDep) -> RunInfo:
        run = active(engine)
        return RunInfo(**run.__dict__)

    @app.get("/forecasts/dates", response_model=Dates, tags=["forecasts"])
    def dates(engine: EngineDep) -> Dates:
        run = active(engine)
        return Dates(run_id=run.run_id, dates=store.forecast_dates(engine, run.run_id))

    @app.get("/forecasts/{day}", response_model=ForecastDay, tags=["forecasts"])
    def forecast_day(
        day: date,
        engine: EngineDep,
        station_id: str | None = None,
        target: Target | None = None,
    ) -> ForecastDay:
        run = active(engine)
        in_run(run, day)
        rows = store.hourly(engine, run.run_id, day, station_id, target.value if target else None)
        points = [Point(**r, local_time=r["ts_utc"].astimezone(LOCAL)) for r in rows]
        return ForecastDay(run_id=run.run_id, date=day, points=points)

    @app.get("/forecasts/{day}/stations", response_model=StationsDay, tags=["forecasts"])
    def stations_day(
        day: date,
        engine: EngineDep,
        window: Annotated[Window, Query(description="Local time window")] = Window.all_day,
    ) -> StationsDay:
        run = active(engine)
        in_run(run, day)
        rows = store.daily_station_summary(engine, run.run_id, day, WINDOWS[window.value])
        meta = {s["station_id"]: s for s in store.all_stations(engine)}
        by_station: dict[str, dict] = {}
        for r in rows:
            entry = by_station.setdefault(r["station_id"], {})
            entry[r["target"]] = r
        result = []
        for sid, targets in by_station.items():
            dep, arr = targets.get("departures", {}), targets.get("arrivals", {})
            observed = bool(dep.get("hours_observed")) and bool(arr.get("hours_observed"))
            fd, fa = float(dep.get("forecast") or 0.0), float(arr.get("forecast") or 0.0)
            ad = float(dep["actual"]) if observed else None
            aa = float(arr["actual"]) if observed else None
            station = meta.get(sid, {"name": sid, "capacity": 0})
            result.append(
                StationDay(
                    station_id=sid,
                    name=station["name"],
                    capacity=station["capacity"],
                    forecast_departures=fd,
                    forecast_arrivals=fa,
                    forecast_net=fa - fd,
                    actual_departures=ad,
                    actual_arrivals=aa,
                    actual_net=(aa - ad) if observed else None,
                )
            )
        result.sort(key=lambda s: s.forecast_net)
        return StationsDay(run_id=run.run_id, date=day, window=window, stations=result)

    return app


app = create_app()
