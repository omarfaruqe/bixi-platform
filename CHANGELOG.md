# Changelog

## 1.1.0 - 2026-10-21
- **Theme.** Self-hosted Inter and JetBrains Mono fonts (no external requests), light and dark
  variants that follow the viewer's system setting, softer borders and rounding, a sidebar tint,
  chart colours from the project palette, and an original logo.
- **Credits.** The footer states that this is an independent project, not affiliated with BIXI.
- **CI fixes.** The API creates its schema on first connection, so a fresh database is healthy
  before the first publish; containers report their health and logs as annotations on failure;
  api and app images get separate tags.

## 1.0.0 - 2026-10-21
First complete version, built in ten steps.

1. **Setup.** Package layout, bilingual Streamlit skeleton (English default, French switch),
   translation catalogs with consistency tests, Canadian number and date formats.
2. **Data.** Downloaders for BIXI trips (2023-2025), the GBFS station feed and Open-Meteo weather;
   station identity by location (historical names linked to live stations within 50 m); a
   50-station study set in one 3 km zone.
3. **Ingestion.** Cleaning rules (UTC hours, April 15 - November 15 season, false starts, long
   trips) and a complete hourly grid of 770,550 station-hours.
4. **Exploration.** Trip analysis and station map pages: daily rhythm, net flow, weekday x hour
   heatmap, season trends.
5. **Features.** Leakage-safe modelling table: demand lags of 24 h or more, Québec holidays,
   festivals, archived day-ahead weather forecasts.
6. **Models.** Three baselines and LightGBM (Poisson), monthly backtests and a six-week holdout;
   80% intervals with conformal calibration. Holdout MAE 1.92 departures per station-hour, 33%
   below "same hour last week".
7. **Serving.** PostgreSQL forecast store, read-only FastAPI service, Demand forecasts page,
   Docker Compose deployment behind Caddy.
8. **Rebalancing.** Hour-by-hour inventory simulation, rule of thumb versus OR-Tools routes,
   planned from forecasts and scored on actual flows: 20% fewer problem hours with 2 trucks.
9. **Dashboard.** Overview with live headline results, Data and methodology page, consistent
   icons, footer credits.
10. **Polish.** Fixed republishing a forecast run on PostgreSQL; store and API tests also run on
    PostgreSQL in CI; CI builds and smoke-tests the Docker stack; command-line and full-app tests;
    final README (EN/FR) with architecture and screenshots; `make check` and `make coverage`.
