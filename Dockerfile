FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DASHBOARD_PASSWORD= \
    DASHBOARD_READONLY=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY apps_catalog.json .
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts

# Seed with scraped reviews so the first boot is useful offline of store APIs
RUN mkdir -p /app/data
COPY data/reviews.db /app/data/reviews.db

EXPOSE 8000

# Cloud hosts inject PORT; default 8000 for local docker runs
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
