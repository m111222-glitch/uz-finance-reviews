#!/usr/bin/env bash
# Permanent free host via GitHub + Render (no credit card on free plan).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="/opt/homebrew/bin:$HOME/.fly/bin:$PATH"

if ! command -v gh >/dev/null; then
  echo "Installing GitHub CLI…"
  brew install gh
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Log in to GitHub (browser)…"
  gh auth login --web --git-protocol https --hostname github.com
fi

echo "GitHub: $(gh api user --jq .login)"

if [[ ! -f data/reviews.db ]]; then
  echo "Missing data/reviews.db — run: source .venv/bin/activate && python scripts/sync.py"
  exit 1
fi

if [[ ! -d .git ]]; then
  git init -b main
fi

git add -A
git status --short | head -40
if ! git diff --cached --quiet 2>/dev/null || ! git rev-parse HEAD >/dev/null 2>&1; then
  git commit -m "Deploy UZ Finance Reviews dashboard" || true
fi

REPO_NAME="${GITHUB_REPO_NAME:-uz-finance-reviews}"
OWNER="$(gh api user --jq .login)"
FULL="$OWNER/$REPO_NAME"

if gh repo view "$FULL" >/dev/null 2>&1; then
  echo "Repo exists: https://github.com/$FULL"
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$FULL.git"
else
  echo "Creating public repo $FULL…"
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
fi

git push -u origin main 2>&1 || git push -u origin HEAD:main

echo
echo "============================================================"
echo "  GitHub:  https://github.com/$FULL"
echo
echo "  Next — one click on Render (free, no card):"
echo "  1. Open https://dashboard.render.com/select-repo?type=web"
echo "  2. Connect GitHub and pick: $FULL"
echo "  3. Settings:"
echo "       Runtime:        Python"
echo "       Build command:  pip install -r requirements.txt"
echo "       Start command:  uvicorn backend.main:app --host 0.0.0.0 --port \$PORT"
echo "       Health check:   /api/health"
echo "  4. Env vars:"
echo "       DASHBOARD_PASSWORD=   (empty)"
echo "       DASHBOARD_READONLY=1"
echo "       PYTHON_VERSION=3.12.0"
echo
echo "  Or Blueprint: New → Blueprint → select $FULL (uses render.yaml)"
echo
echo "  Your permanent URL will look like:"
echo "  https://uz-finance-reviews.onrender.com"
echo "============================================================"

# Open Render + GitHub for the user
open "https://github.com/$FULL" 2>/dev/null || true
open "https://dashboard.render.com/blueprints/new" 2>/dev/null || true

echo "https://github.com/$FULL" > data/github_url.txt
