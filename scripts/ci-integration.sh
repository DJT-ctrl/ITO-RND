#!/usr/bin/env bash
# Local reproduction of the CI Docker Compose integration job (issue #10).
# Boots an isolated compose project (db + migrate + api + prometheus), seeds
# fixtures, runs pytest integration. Uses dedicated host ports so it does not
# collide with a developer stack already on 5432/8000/9090.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ito-ci-integration}"
export POSTGRES_USER="${POSTGRES_USER:-ito}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ci_test_password}"
export POSTGRES_DB="${POSTGRES_DB:-ito_posts}"
export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-ci_grafana_password}"
export GEMINI_API_KEY="${GEMINI_API_KEY:-ci-fake-gemini-key}"
export GOOGLE_API_KEY="${GOOGLE_API_KEY:-$GEMINI_API_KEY}"
export API_AUTH_ENABLED="${API_AUTH_ENABLED:-false}"
export CI_INTEGRATION_STUBS=true
export CI_EVALUATE_STUB=true
export DB_HOST_PORT="${DB_HOST_PORT:-15432}"
export API_HOST_PORT="${API_HOST_PORT:-18000}"
export PROMETHEUS_HOST_PORT="${PROMETHEUS_HOST_PORT:-19090}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${DB_HOST_PORT}/${POSTGRES_DB}"
export API_BASE_URL="http://localhost:${API_HOST_PORT}"
export PROMETHEUS_BASE_URL="http://localhost:${PROMETHEUS_HOST_PORT}"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.ci.yml)

# macOS often has python3 but not python; prefer repo .venv when present.
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "No Python found. Create a venv first:" >&2
  echo "  python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

cleanup() {
  "${COMPOSE[@]}" down -v || true
}
trap cleanup EXIT

"${COMPOSE[@]}" up -d --build db migrate api prometheus
"${COMPOSE[@]}" ps

echo "Waiting for API health at ${API_BASE_URL}..."
for i in $(seq 1 36); do
  if curl -fsS "${API_BASE_URL}/health" >/dev/null 2>&1; then
    echo "health ok"
    break
  fi
  if [[ "$i" -eq 36 ]]; then
    echo "API did not become healthy"
    "${COMPOSE[@]}" logs api migrate db
    exit 1
  fi
  sleep 5
done

"$PYTHON" scripts/integration-seed.py

"$PYTHON" -m pytest tests/integration -m integration -v --junitxml=integration-results.xml
echo "integration ok"
