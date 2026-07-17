#!/usr/bin/env bash
# Pre-start helper for ito-stack.service (issue #13).
# When ITO_AWS_SECRET_ID / ITO_AWS_SECRET_ARN is set, materialize runtime.env.
# When unset (local systemd experiments), skip AWS fetch so Compose can use .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ITO_ENV_FILE:-/run/ito/runtime.env}"
SECRET="${ITO_AWS_SECRET_ARN:-${ITO_AWS_SECRET_ID:-}}"

if [[ -z "$SECRET" ]]; then
  echo "ITO_AWS_SECRET_ID unset — skipping Secrets Manager fetch (local .env mode)"
  exit 0
fi

mkdir -p "$(dirname "$OUT")"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" "$ROOT/scripts/fetch_aws_secrets.py" \
  --out "$OUT" \
  --require-production-keys
