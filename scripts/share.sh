#!/usr/bin/env bash
# Start (or reuse) the dashboard and publish a public Cloudflare URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
cd "$ROOT"

# Load .env if present
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# Empty password = open share (no login). Override via .env if needed.
PASSWORD="${DASHBOARD_PASSWORD-}"
READONLY="${DASHBOARD_READONLY:-1}"
SECRET="${DASHBOARD_SECRET:-uz-finance-share-secret}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install with: brew install cloudflared"
  exit 1
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

health_ok() {
  curl -sf "http://${HOST}:${PORT}/api/health" >/dev/null 2>&1
}

if ! health_ok; then
  echo "Starting dashboard on ${HOST}:${PORT}…"
  export DASHBOARD_PASSWORD="${PASSWORD}"
  export DASHBOARD_READONLY="${READONLY}"
  export DASHBOARD_SECRET="${SECRET}"
  export DASHBOARD_COOKIE_SECURE="${DASHBOARD_COOKIE_SECURE:-1}"
  nohup uvicorn backend.main:app --host "${HOST}" --port "${PORT}" \
    >"$ROOT/data/server.log" 2>&1 &
  echo $! >"$ROOT/data/server.pid"
  for _ in $(seq 1 30); do
    health_ok && break
    sleep 0.3
  done
  if ! health_ok; then
    echo "Server failed to start. See data/server.log"
    exit 1
  fi
else
  echo "Dashboard already running on ${HOST}:${PORT}"
fi

echo
if [[ -n "$PASSWORD" ]]; then
  echo "Password protection: ON"
  echo "Share password: ${PASSWORD}"
else
  echo "Password protection: OFF (open link for colleagues)"
fi
echo "Read-only sync lock: ${READONLY}"
echo
echo "Starting public tunnel… (Ctrl+C stops the tunnel only)"
echo

# Capture URL from cloudflared logs while streaming
LOG="$ROOT/data/tunnel.log"
: >"$LOG"
cloudflared tunnel --url "http://${HOST}:${PORT}" --no-autoupdate 2>&1 | tee "$LOG" &
TUNNEL_PID=$!
echo $TUNNEL_PID >"$ROOT/data/tunnel.pid"

# Wait for trycloudflare URL
URL=""
for _ in $(seq 1 40); do
  URL="$(grep -Eo 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true)"
  if [[ -n "$URL" ]]; then
    break
  fi
  sleep 0.4
done

echo
echo "============================================================"
if [[ -n "$URL" ]]; then
  echo "  Public URL:  $URL"
  echo "$URL" >"$ROOT/data/public_url.txt"
else
  echo "  Public URL:  (see tunnel log above)"
fi
if [[ -n "$PASSWORD" ]]; then
  echo "  Password:    $PASSWORD"
else
  echo "  Access:      open (no password)"
fi
echo "  Sync:        $([ "$READONLY" = "1" ] && echo disabled || echo allowed)"
echo "============================================================"
echo
echo "Keep this terminal open while sharing."
wait "$TUNNEL_PID"
