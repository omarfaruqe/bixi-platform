# Design decisions

Short records of choices a reviewer might question. Update as the project evolves.

## 1. Tooling split
- **Polars + Parquet**: all transformation and feature engineering.
- **DuckDB**: ad-hoc SQL exploration over Parquet only (notebooks, quick checks).
- **PostgreSQL + PostGIS**: serving layer (stations, forecasts, simulation results). PostGIS is
  kept only if Step 8 uses real spatial queries (nearest stations, distance matrix for routing).
  If it does not, drop it and use plain PostgreSQL.
- **FastAPI** sits between the dashboard and the data so the forecast service can be reused and
  tested independently of Streamlit.

## 2. What we forecast
We forecast **observed** hourly departures and arrivals per station. Observed trips are censored:
a station that is empty cannot record a departure, and a full station cannot record an arrival.
Observed trips therefore understate true demand, and historical trips alone cannot identify
stockouts. This caveat is shown in the application.

## 3. Evaluation protocol (fixed before modelling)
- Baselines: seasonal naive (same hour last week); mean by station x hour x day type.
- Models: LightGBM with count-appropriate objectives (Poisson / Tweedie) compared with L2.
- Validation: rolling-origin backtests, never random splits; final holdout is a late-season block.
- Metrics: MAE, RMSE, and Poisson deviance, reported overall and by station, hour, weather, and
  day type. Quantile models for 80% prediction intervals; report interval coverage.
- Leakage rule: 24-hour forecasts use only information available at prediction time. Weather
  inputs are forecasts (or lagged observations), never observed future weather.

## 4. Station selection (Step 2)
Choose 50 stations after checking continuity across 2023-2025. Selection criteria and the
resulting mix (volume, borough, station type) will be documented here, and the sample should not
be only the busiest stations.

## 5. Rebalancing simulation (Step 8)
Starting inventory and capacity are assumptions, not observations. The simulation is a scenario
analysis with sensitivity runs over those assumptions. Strategies compared: no rebalancing,
a rule-based heuristic, and the OR-Tools plan with truck capacity and time-window constraints.
Metrics defined up front: projected empty-station hours, projected full-station hours, and
truck distance / number of moves.

## 6. Internationalisation
JSON catalogs (`src/bixi/locales`), English default and fallback. Babel with Canadian locales
(`en_CA`, `fr_CA`) formats numbers, percentages, and dates. Station names are never translated.
Tests fail when a key exists in one language but not the other, when placeholders differ, or
when code references a key that does not exist.

## 7. Minimum impressive version
If time runs short, ship Steps 1-6 plus a basic dashboard: validated data, baselines vs LightGBM
with backtests, station map, bilingual UI, live demo.
