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

## 4. Station identity and selection (Step 2)
The trip files have no station id. Names drift between years (case, accents, spacing, and real
renames), so 1,724 historical names describe far fewer physical stations. A station is
identified by **location**: each historical name is linked to the nearest station in the live
GBFS feed within 50 m, which gives a stable `station_id` and a dock `capacity`
(`src/bixi/stations/identity.py`). Linked names carry 78-85% of trip events; the rest are mostly
off-island, retired, or relocated stations. 213 live stations have more than one historical name.

The 50 study stations (`reference/selected_stations.csv`, produced by
`scripts/select_stations.py`) must meet all of:
- on the island of Montréal, inside one 3 km service zone (downtown, Old Montréal, the Plateau,
  the universities). One zone keeps the Step 8 truck routing realistic;
- at least 2,000 starts + ends in each of 2023, 2024 and 2025;
- no year below 50% of the station's busiest year (screens out relocations, unlinked renames
  and long construction, e.g. Ste-Catherine / du Fort and Métro Berri-UQAM).

From the 194 eligible stations, the selection takes a third from each volume tercile (low,
medium, high) and spreads picks out geographically (greedy max-min distance). Result: 33 street,
8 park or plaza, 7 transit, 2 campus stations; 14-47 docks each. The selection is deterministic.

Limitation: the sample is urban-core only, so results do not describe outer boroughs.

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

## 8. Cleaning rules (from the Step 2 profile)
- **Time**: `STARTTIMEMS` / `ENDTIMEMS` are UTC epoch milliseconds. Aggregate on UTC hours and
  derive local (`America/Toronto`) calendar features, so the DST fall-back hour is not merged.
- **Season**: model April 15 - November 15. December-March is a small winter network (about
  2-3% of trips) with different behaviour; it is excluded and documented, not imputed.
- **Coordinates**: 0.0 and -1.0 are missing-value sentinels and become null.
- **Departures**: every trip with a start station counts as a departure at its start hour.
- **Arrivals**: a trip counts as an arrival only if it has an end time and an end station
  (0.3-0.6% of trips have no end).
- **False starts**: same-station trips under 60 s are re-docks, not demand; dropped from both.
- **Long trips**: trips over 24 h keep their departure but not their arrival (the bike was
  likely recovered by staff).
- **Station id**: attached through `data/processed/station_crosswalk.csv`; trips at names that
  do not link to a live station keep `station_id = null` and are outside the study set.

## 9. Ingestion outputs (Step 3)
`python -m bixi.ingest` (or `make ingest`) applies section 8 with Polars and writes:
- `data/processed/trips_clean/<year>.parquet`: every trip with station ids and
  `is_departure` / `is_arrival` flags (98.1-98.8% of trips are kept as departures).
- `data/processed/hourly_station.parquet`: 50 stations x 15,411 season hours = 770,550 rows,
  with departures and arrivals. Hours with no trips are stored as zeros (16% of station-hours);
  dropping them would teach a model that quiet hours never happen.
- `data/processed/hourly_system.parquet`: network-wide departures per hour.
- `data/processed/ingest_report.txt`: the validation summary.

Checks against the independent DuckDB profile: season counts are 91-95% (median) of each
station's full-year events, the remainder being winter service and the dropped false starts.
The few lower ratios belong to winter-service stations (e.g. Messier / St-Joseph). Peak hour is
17:00 local; each daylight-saving fall-back day has 25 hours, kept apart because the grid is UTC.

Observed extremes are kept, not clipped: Métro St-Laurent (24 docks) recorded 229 arrivals in one
hour on a festival evening, when BIXI runs staffed overflow docking. Such hours are an argument
for event features in Step 5, and another reminder that observed trips are not station capacity.

## 10. Trip analysis and station map (Step 4)
Pages: *Trip analysis* (daily rhythm, hourly net flow, weekday x hour heatmap, season trend per
year) and *Station map* (net flow by time window, top stations losing and gaining bikes).
Aggregations live in `src/bixi/analysis/patterns.py`; figures in `src/bixi/app/charts.py`; both
are Streamlit-free and tested. Québec holidays (`src/bixi/features/calendar.py`) define the
weekday / weekend / holiday day types and will be reused as model features in Step 5.

Chart colours come from a validated colour-blind-safe palette with fixed roles: departures blue,
arrivals orange, years blue / orange / aqua in fixed order; net flow is diverging blue (gains
bikes) to red (loses bikes) with a grey midpoint. The app accent is the same blue, so red only
ever means "losing bikes". The map's colour scale is capped at the 90th percentile of absolute
net flow so one extreme station does not wash out the rest. All numbers, hours, weekday and
month names are formatted for the selected language.

Findings (2023-2025 season, 50 stations):
- Weekday departures peak at 17:00 with a smaller 8:00 peak; weekends have one afternoon peak
  (15:00-16:00) and about 90% of weekday volume.
- Commuting moves bikes from the Plateau to downtown in the morning and back in the evening.
  On weekday mornings (7-10 h) Plateau stations such as Marquette / Laurier lose about 21 bikes,
  while Square-Victoria gains about 125 bikes, 339% of its 37 docks.
- Several downtown stations gain more than their whole dock count in the morning peak
  (Square-Victoria, Square Viger, Wellington / Queen, University / Milton). That change cannot be
  absorbed without moving bikes, whatever the starting inventory, which is the case for Step 8.
- Over a full weekday flows do not balance (Berri / Cherrier loses about 89 bikes a day), so
  rebalancing already happens in operations and is invisible in trip data.
- The busiest day in the sample is 2025-06-11 (10,040 departures at the 50 stations).

## 11. Modelling table and leakage-safe features (Step 5)
`python -m bixi.features` (or `make features`) writes `data/processed/features.parquet`: one row
per study station and season hour (770,550 rows), the two targets (departures, arrivals) and the
feature groups listed in `src/bixi/features/build.py` (`FEATURE_GROUPS`).

A forecast is issued at time T for hours T+1 ... T+24, so every feature for hour t is known at
t - 24 h or earlier, or is known far ahead:
- **Calendar**: local hour, weekday, weekend, Québec holiday, month, day of season, year.
- **Station**: id, docks, location, volume tier, station type.
- **Demand lags**: 24 h, 48 h, 1 week and 2 weeks back, the mean of the same hour over the last
  four weeks, and the 24-hour total ending 24 h earlier. Lags join on shifted timestamps, so they
  never reach across the winter gap or slip at DST changes. Network-wide departures 24 h and
  1 week back.
- **Events**: Jazz festival, Francos, Grand Prix and Osheaga, 2023-2025, dates checked against
  published sources (`reference/events.csv`, one source URL per row). Features: any event that
  day, and distance from the station to the nearest active venue.
- **Weather, production**: archived day-ahead forecasts (`fc_*`, Open-Meteo Previous Runs API,
  `*_previous_day1`, about 24 h lead), downloaded with `python -m bixi.download weather-forecast`.
- **Weather, oracle only**: observed weather (`obs_*`, ERA5). It is not available a day ahead, so
  it is used only to measure how much perfect weather knowledge would add.

Early signal checks: rain hours on summer weekday evenings have about 24% fewer departures;
station-hours within 1 km of an active festival venue have about twice the evening arrivals (partly
because those stations are busy anyway). Tests check lag offsets, the 24-hour minimum, the winter
gap, per-station isolation, and that production features contain no observed weather or targets.

Day-ahead forecast coverage (Open-Meteo `best_match`): 2024 and 2025 have every variable; 2023
has temperature only (most archives start in January 2024). Forecast quality against observed
weather: temperature mean absolute error 1.3-1.6 C, rain/no-rain agreement about 90% (2024-2025).
Consequence for Step 6: the production model trains on 2024 data with full forecast weather and is
evaluated on 2025. 2023 is still used for the baselines and the observed-weather (oracle)
comparison, and a variant trained on 2023-2025 with temperature-only weather for 2023 is
compared against it.

## 12. Forecasting models (Step 6)
`python -m bixi.models` runs the backtests, the holdout and the final training; results are in
`docs/model_results.md` (generated) and `data/processed/model_results/` (read by the dashboard).
Experiment tracking is this versioned report plus its tables; MLflow was dropped as unnecessary
at this scale.

**Protocol (fixed before results).** Four monthly backtest folds in 2025 (June-September) and one
holdout, 2025-10-01 to 2025-11-15, evaluated once. Each model trains on 2024 data plus 2025 data up
to 14 days before the cutoff and early-stops on those 14 days. Baselines use the same windows.

**Results, holdout (backtest in brackets), mean absolute error in trips per station-hour:**

| | Departures | Arrivals |
|---|---|---|
| Same hour last week | 2.88 (3.30) | 2.86 (3.28) |
| 4-week same-hour average (best baseline) | 2.62 (2.88) | 2.59 (2.87) |
| **LightGBM, Poisson (main)** | **1.92 (2.47)** | **1.90 (2.45)** |
| Skill vs same hour last week | 33.5% (25.0%) | 33.6% (25.3%) |
| Skill vs best baseline | 26.8% (14.0%) | 26.9% (14.5%) |

- **Objective.** Poisson beat Tweedie and squared error on MAE and Poisson deviance in both
  periods, as expected for counts.
- **Weather.** Day-ahead forecasts reduce MAE by 7-8% on the holdout (about 6% in the backtests)
  versus no weather, and by about a third in rainy hours (1.84 vs 2.80 departures). Observed
  weather (not deployable) would gain only a further 0-3%, so day-ahead forecasts capture most of
  the value of weather.
- **2023 data.** Adding 2023 (temperature-only forecasts) lowers MAE by about 1% in both periods.
  The main model keeps 2024+ for now, because every training row then has complete weather; this
  is a candidate change once more seasons are available.
- **Holidays.** On holidays the model's MAE is 1.94 versus 3.95 for the same-hour-last-week
  baseline.
- **What it relies on.** Recent demand dominates (the 4-week same-hour mean alone is 58-72% of
  the gain), then station, hour, network activity and weather.

**Prediction intervals (80%).** LightGBM quantile models (10th and 90th percentiles) gave 75%
coverage. Split conformal calibration on the 14 days before the cutoff widens them slightly; the
holdout coverage is then 79.8% (departures) and 79.7% (arrivals). A plain Poisson interval around
the mean forecast reaches 81-82% overall but only by over-covering quiet hours (94%) while
covering 62% of the busiest ones (15+ trips per hour), where rebalancing decisions are made.
Limitation: coverage of the calibrated intervals still varies with volume (about 89% in quiet
hours, 75% in the busiest); calibrating separately by volume band is the next refinement.

**Final models** (`data/models/`, not committed): mean, 10th and 90th percentile models per
target, trained on 2024-2025 through 2025-11-14, with the conformal margins in `manifest.json`.
Step 7 serves them.

## 13. Forecast store and API (Step 7)
**Store.** PostgreSQL 16 (`bixi-db`) holds `stations`, `forecast_runs` and `forecasts` (one row per
run, station, target and hour: forecast, 80% interval, and the actual count when known). Schema
and queries use SQLAlchemy Core with portable types, so tests run on SQLite and production on
PostgreSQL (also tested against a local PostgreSQL 16). PostGIS was not needed: no step queries
geometry, and distances are computed in Python. Publishing a run is one transaction and never
edits earlier runs; exactly one run is active, and `python -m bixi.forecast activate <run>`
switches back if a run is wrong.

**API.** FastAPI (`bixi-api`), read-only: `/health`, `/stations`, `/run`, `/forecasts/dates`,
`/forecasts/{date}` (hourly, filter by station and target) and `/forecasts/{date}/stations` (net
change per station for all day or a peak window). Times are returned in UTC and in local time with
the offset, so the repeated hour on the autumn DST change stays unambiguous. The dashboard reads
forecasts only through the API (`BIXI_API_URL`), which is the decoupling planned in section 1.

**What is served, and why.** BIXI publishes trips after the fact, so a forecast for "the next 24
hours from now" has no recent demand to lag on. The active run therefore replays the holdout:
genuine day-ahead forecasts for 2025-10-01 to 2025-11-14 from the model trained through
2025-09-30, shown with what actually happened. `python -m bixi.forecast export-model --start ...`
applies the final models to any later period (for example 2026, once published) and refuses dates
inside their training period, so a run can never show in-sample predictions as forecasts.

**Flow.** Run files are built on the Mac (`export-holdout` or `export-model`), copied to the server
(about 2 MB) and loaded inside the API container with `python -m bixi.forecast publish`. The server
needs neither LightGBM nor the large backtest outputs.
