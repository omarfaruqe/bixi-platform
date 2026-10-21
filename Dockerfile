FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first so code changes do not reinstall them.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[app,data]"

# Small reference files (station list, network) and the Streamlit theme are part of the image.
# The hourly tables are mounted read-only at /data/processed (see deploy/docker-compose.yml).
COPY reference ./reference
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 10001 bixi
USER bixi

ENV BIXI_DATA_DIR=/data \
    BIXI_REFERENCE_DIR=/app/reference

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "src/bixi/app/main.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
