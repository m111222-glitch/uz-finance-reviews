#!/bin/sh
set -e
DATA_DIR="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"
if [ ! -f "$DATA_DIR/reviews.db" ] && [ -f /app/seed/reviews.db ]; then
  echo "Seeding $DATA_DIR/reviews.db from image"
  cp /app/seed/reviews.db "$DATA_DIR/reviews.db"
fi
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
