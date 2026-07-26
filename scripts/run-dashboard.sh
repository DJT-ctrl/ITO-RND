#!/usr/bin/env bash
# Run the local Streamlit dev dashboard (.venv required).
# UI versions — use git checkout to switch:
#   main              → old UI (legacy pages, no top nav chrome)
#   feat/new-ui       → new UI (default — run this script here)
#   feat/vercel-public → public demo is Vercel only: https://ito-public-demo.vercel.app

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
STREAMLIT="$ROOT/.venv/bin/streamlit"

if [[ ! -x "$STREAMLIT" ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

case "$BRANCH" in
  feat/new-ui)
    echo "Starting NEW UI dashboard on http://localhost:8501 (branch: $BRANCH)"
    ;;
  main|pre-feedback-loop)
    echo "Starting OLD UI dashboard on http://localhost:8501 (branch: $BRANCH)"
    ;;
  feat/vercel-public)
    echo "Warning: feat/vercel-public is the public API branch."
    echo "  Local Streamlit here may differ from https://ito-public-demo.vercel.app"
    echo "  For day-to-day dev, use: git checkout feat/new-ui"
    ;;
  *)
    echo "Starting dashboard on http://localhost:8501 (branch: $BRANCH)"
    ;;
esac

# Prefer crash-resistant detached mode when the IDE keeps killing the server:
#   scripts/keep-dashboard-alive.sh --detach
#   scripts/keep-dashboard-alive.sh --stop

exec "$STREAMLIT" run dashboard/app.py --server.headless true --server.port 8501
