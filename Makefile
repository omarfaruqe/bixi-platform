.PHONY: install test lint format app api clean stations ingest features data rebalance

install:
	pip install -e ".[app,data,ml,api,opt,dev]"

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

features:
	python -m bixi.features

data: stations ingest features

rebalance:
	python -m bixi.rebalancing

app:
	streamlit run src/bixi/app/main.py

api:
	uvicorn bixi.api.main:app --reload --port 8000

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
