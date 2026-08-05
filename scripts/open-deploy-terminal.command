#!/bin/bash
# Double-click this file in Finder, or open from Terminal, to deploy permanently.
cd "$(dirname "$0")/.."
export PATH="$HOME/.fly/bin:/opt/homebrew/bin:$PATH"
echo "UZ Finance Reviews — permanent deploy to Fly.io"
echo "================================================"
./scripts/deploy-fly.sh
echo
read -r -p "Press Enter to close…"
