#!/usr/bin/env bash
# Run docker compose with AWS-injected env for *interpolation* (issue #13).
#
# Service `env_file: ${ITO_ENV_FILE}` injects into containers, but Compose
# ${POSTGRES_PASSWORD} substitution only reads the project `.env` unless we
# also pass --env-file. This wrapper does that when the runtime file exists.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ARGS=()
ENV_FILE="${ITO_ENV_FILE:-}"
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  ARGS+=(--env-file "$ENV_FILE")
fi

exec /usr/bin/docker compose "${ARGS[@]}" "$@"
