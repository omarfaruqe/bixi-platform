FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[app]"

EXPOSE 8501
CMD ["streamlit", "run", "src/bixi/app/main.py", "--server.address=0.0.0.0", "--server.port=8501"]
