#!/usr/bin/env bash
# Permanent host on Fly.io (always-on HTTPS URL; Mac can sleep).
# Run this in Terminal.app (needs interactive browser login once).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.fly/bin:/opt/homebrew/bin:$PATH"

if ! command -v flyctl >/dev/null 2>&1 && ! command -v fly >/dev/null 2>&1; then
  echo "Installing Fly CLI…"
  curl -L https://fly.io/install.sh | sh
  export PATH="$HOME/.fly/bin:$PATH"
fi

FLY="$(command -v flyctl || command -v fly)"

echo "==> Fly CLI: $($FLY version 2>/dev/null | head -1)"

if ! $FLY auth whoami >/dev/null 2>&1; then
  echo
  echo "Logging into Fly.io (browser will open)…"
  echo "Create a free account if you don't have one: https://fly.io/app/sign-up"
  echo
  $FLY auth login
fi

echo "==> Logged in as: $($FLY auth whoami)"

# Unique-ish app name; override with FLY_APP_NAME=...
APP_NAME="${FLY_APP_NAME:-uz-finance-reviews}"
if ! grep -q "^app = " fly.toml 2>/dev/null; then
  echo "app = \"$APP_NAME\"" > fly.toml.tmp
  cat fly.toml >> fly.toml.tmp 2>/dev/null || true
fi

# Ensure seed DB exists for first boot
if [[ ! -f data/reviews.db ]]; then
  echo "No data/reviews.db — run: source .venv/bin/activate && python scripts/sync.py"
  exit 1
fi

# Create app if missing
if ! $FLY apps list 2>/dev/null | grep -q "$APP_NAME"; then
  echo "==> Creating app '$APP_NAME' in region ams…"
  # --generate-name if taken
  if ! $FLY apps create "$APP_NAME" --org personal 2>/dev/null; then
    APP_NAME="uz-finance-reviews-$(whoami | tr -cd 'a-z0-9' | cut -c1-8)"
    echo "Name taken — using $APP_NAME"
    $FLY apps create "$APP_NAME" --org personal
  fi
  # Patch fly.toml app name
  if [[ -f fly.toml ]]; then
    sed -i.bak "s/^app = .*/app = \"$APP_NAME\"/" fly.toml
  fi
else
  echo "==> App '$APP_NAME' already exists"
  sed -i.bak "s/^app = .*/app = \"$APP_NAME\"/" fly.toml 2>/dev/null || true
fi

echo "==> Setting open share env (no password, read-only sync)…"
$FLY secrets set DASHBOARD_PASSWORD="" DASHBOARD_READONLY=1 --app "$APP_NAME" || true

echo "==> Deploying (remote Docker build — may take 2–5 min)…"
$FLY deploy --app "$APP_NAME" --remote-only

URL="https://${APP_NAME}.fly.dev"
echo
echo "============================================================"
echo "  Permanent URL:  $URL"
echo "  Access:         open (no password)"
echo "  Sync:           disabled for public viewers"
echo "============================================================"
echo
echo "Health check:"
curl -sf "$URL/api/health" && echo || echo "(wait ~30s and open the URL in a browser)"
echo "$URL" > data/permanent_url.txt
echo
echo "Done. Share $URL with colleagues — works while the Fly app is deployed."
echo "Re-deploy after code/data updates:  ./scripts/deploy-fly.sh"
