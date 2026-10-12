.PHONY: install test lint format app clean

install:
	pip install -e ".[app,dev]"

test:
	pytest -q

lint:
	ruff check src tests

format:
	ruff format src tests
	ruff check --fix src tests

app:
	streamlit run src/bixi/app/main.py

clean:
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
