# BIXI Demand Forecasting and Rebalancing Platform

🇫🇷 [Version française](README.fr.md)

A bilingual (English / Français) data science project for Montréal's BIXI bike-share system. It
answers: **how many departures and arrivals should we expect at each station, and where should
bicycles be redistributed?**

> **Status:** Step 1 of 10 complete (project setup and bilingual application skeleton).
> A findings summary (model vs. baseline, rebalancing scenarios, live demo link) will be added
> here once Steps 6-9 are done.

## Scope
- 2023-2025 historical trips, narrowed to 50 stations after data quality and continuity checks
- Hourly departure and arrival analysis
- 24-hour demand forecasts with prediction intervals, using weather and calendar features
- Interactive station map
- Rebalancing simulation under explicit assumptions about starting inventory and capacity

**Important limitation:** observed trips are not true demand. Historical trips alone cannot show
actual stockouts or unmet demand, so rebalancing results are scenario estimates. See
[docs/decisions.md](docs/decisions.md).

## Roadmap
| Step | Deliverable | Status |
|---|---|---|
| 1 | Project setup and bilingual application skeleton | Done |
| 2 | Download, inspect, and validate BIXI data | Next |
| 3 | Repeatable ingestion pipeline | |
| 4 | Trip pattern exploration and station maps | |
| 5 | Weather and hourly modelling tables | |
| 6 | Baselines and forecasting model evaluation | |
| 7 | Store and serve forecasts through FastAPI | |
| 8 | Redistribution simulation | |
| 9 | Complete bilingual dashboard | |
| 10 | Documentation, tests, deployment | |

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate
make install        # pip install -e ".[app,dev]"
make test
make app            # http://localhost:8501  (add ?lang=fr for French)
```
Or with Docker: `docker compose up --build`.

## Project layout
```
src/bixi/
  i18n.py            translation + locale-aware formatting
  locales/           en.json, fr.json (all interface text)
  config.py          settings from environment variables
  app/               Streamlit dashboard (registry, state, views)
tests/               i18n consistency and formatting tests
docs/decisions.md    design decisions and evaluation protocol
```

## Language support
English is the default; the sidebar switch changes navigation, filters, chart labels, tooltips,
explanations, and errors. Station names stay in their original form. Numbers, percentages, and
dates follow the selected language (Canadian locales). To add text, add the same key to both
`en.json` and `fr.json`; the tests fail if they diverge.

## Conventions
Code, database columns, and API fields are in English. Data comes from BIXI open data; check the
current terms of use and cite the source before publishing results.
