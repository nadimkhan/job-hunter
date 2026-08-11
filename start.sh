#!/usr/bin/env bash
# ── Job Hunter — Start All Services ───────────────────────────────────────────
# Run from project root: ./start.sh
# Or: bash start.sh

set -e

cd "$(dirname "$0")"

# Activate venv
if [ -d ".venv/bin" ]; then
  source .venv/bin/activate
elif [ -d "venv/bin" ]; then
  source venv/bin/activate
else
  echo "ERROR: No virtual environment found in $(pwd)"
  exit 1
fi

echo "[$(date)] Starting Job Hunter..."
echo "  Web UI:    http://localhost:8000"
echo "  Dashboard: http://localhost:8000/web/dashboard"
echo ""

python main.py
