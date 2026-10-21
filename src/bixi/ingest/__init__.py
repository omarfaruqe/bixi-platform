"""Step 3: repeatable ingestion of raw BIXI trips into clean Parquet tables.

raw CSV (one per year)
  -> data/processed/trips_clean/<year>.parquet   every trip, cleaned, with station ids and flags
  -> data/processed/hourly_station.parquet        50 study stations x every season hour (zeros kept)
  -> data/processed/hourly_system.parquet         whole-network departures per season hour

The cleaning rules are documented in docs/decisions.md (section 8) and live in ``rules.py``.
"""
