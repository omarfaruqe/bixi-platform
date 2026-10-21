"""Step 7: publish forecasts to a database and read them back for the API.

A *run* is one published batch of forecasts (one model, one period). Exactly one run is active;
the API serves the active run. Publishing a new run never edits an old one, so a bad run can be
rolled back by re-activating the previous one.
"""
