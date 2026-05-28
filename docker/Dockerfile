# syntax=docker/dockerfile:1
# Minimal image — only for testing downloads (no adb needed)
FROM python:3.12-alpine

WORKDIR /app

COPY scripts/lib.py      scripts/lib.py
COPY scripts/download.py scripts/download.py

CMD ["python3", "scripts/download.py"]
