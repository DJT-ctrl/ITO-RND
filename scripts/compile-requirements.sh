#!/usr/bin/env bash
# Regenerate pinned requirements.txt from requirements.in using Python 3.12
# (matches the API Docker image). Run from repo root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Compiling requirements.in -> requirements.txt (Python 3.12)..."
docker run --rm \
  -v "$ROOT:/app" \
  -w /app \
  python:3.12-slim \
  bash -c "pip install -q 'pip-tools>=7.4.0' && pip-compile requirements.in --resolver=backtracking --strip-extras"

echo "Done. Review git diff and commit requirements.txt."
