#!/usr/bin/env bash
# Local reproduction of the CI Docker Compose smoke job.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cat > .env <<'EOF'
POSTGRES_USER=ito
POSTGRES_PASSWORD=ci_test_password
POSTGRES_DB=ito_posts
GRAFANA_ADMIN_PASSWORD=ci_grafana_password
GEMINI_API_KEY=ci-fake-gemini-key
DATABASE_URL=postgresql://ito:ci_test_password@localhost:5432/ito_posts
API_AUTH_ENABLED=false
EOF
  echo "Wrote temporary .env for smoke test"
fi

docker compose up -d --build db migrate api
trap 'docker compose down -v' EXIT

for i in $(seq 1 30); do
  if curl -fsS http://localhost:8000/health >/dev/null; then
    echo "health ok"
    curl -fsS http://localhost:8000/openapi.json | python -c "import sys,json; json.load(sys.stdin); print('openapi ok')"
    exit 0
  fi
  sleep 5
done

echo "API did not become healthy"
docker compose logs api
exit 1
