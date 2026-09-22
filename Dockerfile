FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DASHBOARD_PASSWORD= \
    DASHBOARD_READONLY=0 \
    AUTO_SYNC_HOURS=3 \
    DATA_DIR=/app/data

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

# Seed DB lives outside the volume mount so first boot can copy it in
RUN mkdir -p /app/data /app/seed
COPY data/reviews.db /app/seed/reviews.db
COPY scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
