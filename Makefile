.PHONY: install test lint format app clean stations ingest data

install:
	pip install -e ".[app,data,dev]"

test:
	pytest -q

lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

stations:
	python scripts/select_stations.py

ingest:
	python -m bixi.ingest

data: stations ingest

app:
	streamlit run src/bixi/app/main.py

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
