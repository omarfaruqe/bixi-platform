# BIXI Demand Forecasting and Rebalancing Platform

[![Live demo](https://img.shields.io/badge/live_demo-103.99.176.180%2Fbixi-2a78d6)](http://103.99.176.180/bixi/)
![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40%2B-FF4B4B?logo=streamlit&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)
[![CI](https://github.com/omarfaruqe/bixi-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/omarfaruqe/bixi-platform/actions/workflows/ci.yml)

🇫🇷 [Version française](README.fr.md)

A bilingual (English / Français) data science project for Montréal's BIXI bike-share system. It
answers: **how many departures and arrivals should we expect at each station, and where should
bicycles be redistributed?**

**Live demo:** <http://103.99.176.180/bixi/> (French: <http://103.99.176.180/bixi/?lang=fr>),
a Streamlit dashboard served with Docker behind Caddy.

> **Status:** Steps 1-8 of 10 complete. Step 9 (completing the bilingual dashboard) is next.

## Findings so far
- **Forecasts beat the baselines.** On a six-week holdout (October 1 - November 14, 2025, never
  seen in training), LightGBM with a Poisson objective has a mean absolute error of 1.92
  departures per station-hour: **33% lower** than "same hour last week" and 27% lower than the
  best simple baseline.
- **Weather forecasts matter, perfect weather barely more.** Day-ahead weather forecasts cut
  error by 7-8% overall and by about a third in rainy hours; knowing the actual weather would add
  only 0-3% more.
- **Honest intervals.** 80% prediction intervals (quantile models + conformal calibration) contain
  the actual count 80% of the time.
- **Forecast-based rebalancing pays off.** Over 45 days, truck routes optimized with OR-Tools from
  the day-ahead forecasts cut station-hours with no bike or no free dock by **20%** (2 trucks, half-full
  starts), against 13% for a rule of thumb, while driving 15% less; that is two thirds of what
  perfect foresight would achieve.
- **Commuting drives imbalance.** On weekday mornings the Plateau loses bikes and downtown
  fills: Square-Victoria gains about 125 bikes between 7 and 10 am, 3.4 times its 37 docks.

Details: [docs/model_results.md](docs/model_results.md) and [docs/decisions.md](docs/decisions.md).

## Scope
- 2023-2025 historical trips (39 million), narrowed to 50 stations after data quality and
  continuity checks
- Hourly departure and arrival analysis, station map
- Day-ahead hourly forecasts with 80% prediction intervals, using lagged demand, Québec calendar,
  events and archived weather forecasts (no future information)
- Forecast store (PostgreSQL) and read-only API (FastAPI)
- Rebalancing simulation under explicit assumptions about starting inventory and capacity

**Important limitation:** observed trips are not true demand. Historical trips alone cannot show
actual stockouts or unmet demand, so rebalancing results are scenario estimates.

## Roadmap
| Step | Deliverable | Status |
|---|---|---|
| 1 | Project setup and bilingual application skeleton | Done |
| 2 | Download, inspect, and validate BIXI data | Done |
| 3 | Repeatable ingestion pipeline | Done |
| 4 | Trip pattern exploration and station maps | Done |
| 5 | Weather and hourly modelling tables | Done |
| 6 | Baselines and forecasting model evaluation | Done |
| 7 | Store and serve forecasts through FastAPI | Done |
| 8 | Redistribution simulation | Done |
| 9 | Complete bilingual dashboard | |
| 10 | Documentation, tests, deployment | Deployed early; final polish pending |

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[app,data,ml,api,dev]"
make test
make data           # stations, ingestion, features (needs the raw data: python -m bixi.download all)
python -m bixi.models   # backtests and final models (macOS: brew install libomp)
make app            # http://localhost:8501  (add ?lang=fr for French)
make api            # http://localhost:8000/docs  (needs DATABASE_URL)
```
Deployment on a server with Docker: [deploy/README.md](deploy/README.md).

## Project layout
```
src/bixi/
  download/          BIXI trips, GBFS stations, Open-Meteo weather and archived forecasts
  stations/          station identity (names -> live station ids) and the 50-station selection
  ingest/            cleaning rules, clean trips and hourly tables (Polars)
  features/          Québec calendar, events, weather, leakage-safe modelling table
  analysis/          trip-pattern aggregations
  models/            baselines, LightGBM, backtests, metrics
  forecast/          forecast runs and the PostgreSQL store
  api/               FastAPI service
  app/               Streamlit dashboard (views, charts, API client)
  locales/           en.json, fr.json (all interface text)
reference/           selected stations, network stations, events (committed)
deploy/              production Docker Compose and guide
docs/                design decisions and model results
tests/               unit, leakage, API and page tests
```

## Language support
English is the default; the sidebar switch changes navigation, filters, chart labels, tooltips,
explanations, and errors. Station names stay in their original form. Numbers, percentages, and
dates follow the selected language (Canadian locales). To add text, add the same key to both
`en.json` and `fr.json`; the tests fail if they diverge.

## Data and conventions
Trip data: [BIXI Montréal open data](https://bixi.com/en/open-data/). Weather: [Open-Meteo](https://open-meteo.com/).
Code, database columns, and API fields are in English.
