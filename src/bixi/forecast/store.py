"""Forecast store: schema, writes and the read queries the API needs.

SQLAlchemy Core with portable types, so production runs on PostgreSQL and tests on SQLite.
Timestamps are stored in UTC; local dates and hours (America/Toronto) are stored alongside them
because the API is queried by local day.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.engine import Engine

metadata = sa.MetaData()

stations = sa.Table(
    "stations",
    metadata,
    sa.Column("station_id", sa.String(16), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("borough", sa.String(100)),
    sa.Column("lat", sa.Float, nullable=False),
    sa.Column("lon", sa.Float, nullable=False),
    sa.Column("capacity", sa.Integer, nullable=False),
    sa.Column("volume_tier", sa.String(16)),
    sa.Column("station_type", sa.String(16)),
)

runs = sa.Table(
    "forecast_runs",
    metadata,
    sa.Column("run_id", sa.String(64), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", sa.String(32), nullable=False),  # "holdout" or "model"
    sa.Column("model_variant", sa.String(64), nullable=False),
    sa.Column("trained_through", sa.Date),
    sa.Column("start_date", sa.Date, nullable=False),
    sa.Column("end_date", sa.Date, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, default=False),
    sa.Column("details", sa.Text),  # JSON: interval level, metrics, notes
)

forecasts = sa.Table(
    "forecasts",
    metadata,
    sa.Column("run_id", sa.String(64), sa.ForeignKey("forecast_runs.run_id"), primary_key=True),
    sa.Column("station_id", sa.String(16), primary_key=True),
    sa.Column("target", sa.String(16), primary_key=True),
    sa.Column("ts_utc", sa.DateTime(timezone=True), primary_key=True),
    sa.Column("local_date", sa.Date, nullable=False),
    sa.Column("local_hour", sa.SmallInteger, nullable=False),
    sa.Column("yhat", sa.Float, nullable=False),
    sa.Column("lo", sa.Float),
    sa.Column("hi", sa.Float),
    sa.Column("actual", sa.Float),  # filled when the observed count is known
    sa.Index("ix_forecasts_run_date", "run_id", "local_date"),
)


def engine_for(url: str) -> Engine:
    engine = sa.create_engine(url, pool_pre_ping=True, future=True)
    if engine.dialect.name == "sqlite":
        # SQLite ignores foreign keys unless asked; enforce them so tests behave like PostgreSQL.
        @sa.event.listens_for(engine, "connect")
        def _foreign_keys(dbapi_connection, _record) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def create_schema(engine: Engine) -> None:
    metadata.create_all(engine)


def _utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; everything stored is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Run:
    run_id: str
    created_at: datetime
    source: str
    model_variant: str
    trained_through: date | None
    start_date: date
    end_date: date
    details: dict


def upsert_stations(engine: Engine, rows: Sequence[dict]) -> None:
    with engine.begin() as conn:
        conn.execute(stations.delete())
        if rows:
            conn.execute(stations.insert(), list(rows))


def publish_run(
    engine: Engine,
    run: Run,
    rows: Iterable[dict],
    activate: bool = True,
    batch_size: int = 20_000,
) -> int:
    """Insert one run and its forecasts in a single transaction; optionally make it active."""
    count = 0
    with engine.begin() as conn:
        # Republishing replaces the run: children first, or the foreign key refuses the delete.
        conn.execute(forecasts.delete().where(forecasts.c.run_id == run.run_id))
        conn.execute(runs.delete().where(runs.c.run_id == run.run_id))
        conn.execute(
            runs.insert(),
            {
                "run_id": run.run_id,
                "created_at": run.created_at,
                "source": run.source,
                "model_variant": run.model_variant,
                "trained_through": run.trained_through,
                "start_date": run.start_date,
                "end_date": run.end_date,
                "is_active": False,
                "details": json.dumps(run.details),
            },
        )
        batch: list[dict] = []
        for row in rows:
            batch.append({"run_id": run.run_id, **row})
            if len(batch) >= batch_size:
                conn.execute(forecasts.insert(), batch)
                count += len(batch)
                batch = []
        if batch:
            conn.execute(forecasts.insert(), batch)
            count += len(batch)
        if activate:
            conn.execute(runs.update().values(is_active=False))
            conn.execute(runs.update().where(runs.c.run_id == run.run_id).values(is_active=True))
    return count


def activate(engine: Engine, run_id: str) -> None:
    with engine.begin() as conn:
        exists = conn.execute(sa.select(runs.c.run_id).where(runs.c.run_id == run_id)).first()
        if exists is None:
            raise KeyError(run_id)
        conn.execute(runs.update().values(is_active=False))
        conn.execute(runs.update().where(runs.c.run_id == run_id).values(is_active=True))


# --- Reads ------------------------------------------------------------------------------------


def active_run(engine: Engine) -> Run | None:
    with engine.connect() as conn:
        row = conn.execute(sa.select(runs).where(runs.c.is_active.is_(True))).mappings().first()
    if row is None:
        return None
    return Run(
        run_id=row["run_id"],
        created_at=_utc(row["created_at"]),
        source=row["source"],
        model_variant=row["model_variant"],
        trained_through=row["trained_through"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        details=json.loads(row["details"] or "{}"),
    )


def list_runs(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(sa.select(runs).order_by(runs.c.created_at.desc())).mappings().all()
    return [dict(r) for r in rows]


def all_stations(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(r) for r in conn.execute(sa.select(stations).order_by(stations.c.name)).mappings()
        ]


def forecast_dates(engine: Engine, run_id: str) -> list[date]:
    query = (
        sa.select(forecasts.c.local_date)
        .where(forecasts.c.run_id == run_id)
        .distinct()
        .order_by(forecasts.c.local_date)
    )
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(query)]


def hourly(
    engine: Engine, run_id: str, day: date, station_id: str | None = None, target: str | None = None
) -> list[dict]:
    query = sa.select(
        forecasts.c.station_id,
        forecasts.c.target,
        forecasts.c.ts_utc,
        forecasts.c.local_hour,
        forecasts.c.yhat,
        forecasts.c.lo,
        forecasts.c.hi,
        forecasts.c.actual,
    ).where(forecasts.c.run_id == run_id, forecasts.c.local_date == day)
    if station_id is not None:
        query = query.where(forecasts.c.station_id == station_id)
    if target is not None:
        query = query.where(forecasts.c.target == target)
    query = query.order_by(forecasts.c.station_id, forecasts.c.target, forecasts.c.ts_utc)
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(query).mappings()]
    for r in rows:
        r["ts_utc"] = _utc(r["ts_utc"])
    return rows


def daily_station_summary(
    engine: Engine, run_id: str, day: date, window: tuple[int, int] = (0, 24)
) -> list[dict]:
    """Per station and target: forecast and actual totals within local hours [start, end)."""
    f = forecasts
    query = (
        sa.select(
            f.c.station_id,
            f.c.target,
            sa.func.sum(f.c.yhat).label("forecast"),
            sa.func.sum(f.c.actual).label("actual"),
            sa.func.count(f.c.actual).label("hours_observed"),
        )
        .where(
            f.c.run_id == run_id,
            f.c.local_date == day,
            f.c.local_hour >= window[0],
            f.c.local_hour < window[1],
        )
        .group_by(f.c.station_id, f.c.target)
        .order_by(f.c.station_id, f.c.target)
    )
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(query).mappings()]
