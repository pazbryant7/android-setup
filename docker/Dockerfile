# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY profiles/ profiles/
COPY tests/ tests/
RUN python3 -m pip install --no-cache-dir '.[dev]'

CMD ["pytest", "-m", "not live", "tests"]
