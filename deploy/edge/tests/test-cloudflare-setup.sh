#!/usr/bin/env bash
# Test cloudflare-setup.sh against a mock Cloudflare API (mock_cf_api.py).
# Verifies the whole control flow with no real Cloudflare account:
#   • zone verify → create-record branch (first run, POST)
#   • zone verify → update-record branch (second run, PUT — idempotent re-run)
#   • all five zone settings + HSTS are PATCHed
# Requires only python3 + curl (no Docker).
set -u

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
EDGE="${ROOT}/deploy/edge"
PORT="${CF_MOCK_PORT:-8787}"
LOG="$(mktemp)"

PASS=0; FAIL=0
green() { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
red()   { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }
have()  { case "$2" in *"$1"*) green "$3";; *) red "$3 — missing [$1]";; esac; }

python3 "${EDGE}/tests/mock_cf_api.py" "$PORT" 2>"$LOG" &
MOCK_PID=$!
cleanup() { kill "$MOCK_PID" 2>/dev/null || true; wait "$MOCK_PID" 2>/dev/null || true; rm -f "$LOG"; }
trap cleanup EXIT
sleep 1

export CF_API_BASE="http://127.0.0.1:${PORT}/client/v4"
export CF_API_TOKEN="test-token"
export CF_ZONE_ID="zone123"
export EDGE_DOMAIN="api.example.com"
export ORIGIN_IP="203.0.113.10"

echo "── cloudflare-setup.sh against mock API ──"
run1="$("${EDGE}/cloudflare/cloudflare-setup.sh" 2>&1)"
have "created new record" "$run1" "first run creates the DNS record"

run2="$("${EDGE}/cloudflare/cloudflare-setup.sh" 2>&1)"
have "updated existing record" "$run2" "second run updates it (idempotent)"

log="$(cat "$LOG")"
have "POST /client/v4/zones/zone123/dns_records"           "$log" "record created via POST"
have "PUT /client/v4/zones/zone123/dns_records/rec-created" "$log" "record updated via PUT"
for s in ssl always_use_https automatic_https_rewrites min_tls_version tls_1_3 security_header; do
    have "PATCH /client/v4/zones/zone123/settings/${s}" "$log" "setting '${s}' applied"
done

echo
printf ' RESULT: \033[32m%d passed\033[0m, %s%d failed\033[0m\n' "$PASS" "$([ "$FAIL" -gt 0 ] && printf '\033[31m' || printf '\033[32m')" "$FAIL"
[ "$FAIL" -eq 0 ]
