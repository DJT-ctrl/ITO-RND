#!/usr/bin/env bash
# End-to-end test for the ITO edge (Web Traffic & Security Guard).
#
# Two phases, both against the REAL config:
#   Phase 1  `nginx -t` on the shipped nginx.conf + real Cloudflare snippets +
#            rendered template — proves the config that goes to production is
#            syntactically valid.
#   Phase 2  Stand up the edge in front of a mock upstream on a private network
#            with a simulated Cloudflare client and a simulated attacker, and
#            assert every routing/security behaviour with curl.
#
# Requires Docker. Self-contained — no domain, Cloudflare account, or app
# dependencies needed. Exits non-zero if any assertion fails.
set -u

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
EDGE="${ROOT}/deploy/edge"
COMPOSE_FILE="${EDGE}/tests/docker-compose.test.yml"
DC="docker compose -f ${COMPOSE_FILE}"

PASS=0
FAIL=0
green() { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
red()   { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }

assert_eq() {       # desc expected actual
    if [ "$2" = "$3" ]; then green "$1"; else red "$1 — expected [$2], got [$3]"; fi
}
assert_contains() { # desc needle haystack
    case "$3" in *"$2"*) green "$1";; *) red "$1 — missing [$2]";; esac
}
assert_not_contains() { # desc needle haystack
    case "$3" in *"$2"*) red "$1 — unexpectedly found [$2]";; *) green "$1";; esac
}

cleanup() {
    echo
    echo "→ Tearing down test stack…"
    $DC down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Run a shell command inside one of the client containers.
in_cf()       { $DC exec -T cf sh -c "$1"; }
in_attacker() { $DC exec -T attacker sh -c "$1"; }

echo "════════════════════════════════════════════════════════════════"
echo " ITO edge test — $(basename "$COMPOSE_FILE")"
echo "════════════════════════════════════════════════════════════════"

# --- Prep: origin cert (self-signed) so Nginx can bind :443 ----------------
echo
echo "→ Ensuring a self-signed origin cert exists…"
"${EDGE}/certbot/gen-selfsigned.sh" "${EDGE}/certs" localhost >/dev/null
echo "  ok"

# ── Phase 1: validate the REAL shipped config ──────────────────────────────
echo
echo "── Phase 1: nginx -t on the production config (real CF snippets) ──"
if docker run --rm \
        -e SERVER_NAME=api.example.com \
        -e UPSTREAM_API=127.0.0.1:8000 \
        -e TLS_CERT=/etc/nginx/certs/fullchain.pem \
        -e TLS_KEY=/etc/nginx/certs/privkey.pem \
        -v "${EDGE}/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
        -v "${EDGE}/nginx/snippets:/etc/nginx/snippets:ro" \
        -v "${EDGE}/nginx/templates:/etc/nginx/templates:ro" \
        -v "${EDGE}/certs:/etc/nginx/certs:ro" \
        --tmpfs /etc/nginx/conf.d \
        nginx:1.27-alpine nginx -t >/tmp/ito-nginx-t.log 2>&1; then
    green "production nginx.conf + snippets + template pass 'nginx -t'"
else
    red "'nginx -t' failed on production config"
    cat /tmp/ito-nginx-t.log
fi

# ── Phase 2: behavioural tests ─────────────────────────────────────────────
echo
echo "── Phase 2: bring up edge + mock upstream + clients ──"
$DC up -d --quiet-pull >/dev/null 2>&1 || $DC up -d

echo "→ Waiting for the edge to answer…"
ready=0
for _ in $(seq 1 30); do
    code="$(in_cf "curl -sk -o /dev/null -w '%{http_code}' --max-time 2 https://edge/health" 2>/dev/null || echo 000)"
    if [ "$code" = "200" ]; then ready=1; break; fi
    sleep 1
done
if [ "$ready" != "1" ]; then
    red "edge did not become ready"
    echo "── edge logs ──"; $DC logs edge | tail -30
    echo; echo "RESULT: ${PASS} passed, ${FAIL} failed"; exit 1
fi
green "edge is serving HTTPS /health (200)"

echo
echo "── Routing & TLS ──"
# Health routes to the upstream.
body="$(in_cf "curl -sk https://edge/health")"
assert_contains "GET /health proxied to upstream" '"status":"ok"' "$body"

# HTTP → HTTPS redirect (not for ACME).
redir="$(in_cf "curl -s -o /dev/null -w '%{http_code} %{redirect_url}' http://edge/anything")"
assert_eq "HTTP /anything → 301 redirect to HTTPS" "301 https://edge/anything" "$redir"

# ACME challenge served over plain HTTP, NOT redirected.
acme="$(in_cf "curl -s http://edge/.well-known/acme-challenge/probe")"
assert_eq "ACME HTTP-01 path served over HTTP (no redirect)" "acme-ok" "$acme"

# X-Forwarded-Proto reaches the app as https. (HTTP/2 lowercases header names,
# so normalise the dump to lowercase and match lowercase needles.)
xfp="$(in_cf "curl -sk -D - -o /dev/null https://edge/ | tr -d '\r' | tr 'A-Z' 'a-z'")"
assert_contains "X-Forwarded-Proto=https propagated to upstream" "x-echo-xfp: https" "$xfp"

echo
echo "── Real client-IP restoration ──"
# The edge must restore the true visitor IP from CF-Connecting-IP and forward
# it as X-Real-IP to the upstream.
echo_ip="$(in_cf "curl -sk -D - -o /dev/null -H 'CF-Connecting-IP: 203.0.113.77' https://edge/health | tr -d '\r' | tr 'A-Z' 'a-z'")"
assert_contains "CF-Connecting-IP restored → X-Real-IP to upstream" "x-echo-real-ip: 203.0.113.77" "$echo_ip"

echo
echo "── Origin lockdown (Cloudflare-only) ──"
# Attacker connecting straight to the origin IP is rejected.
acode="$(in_attacker "curl -sk -o /dev/null -w '%{http_code}' https://edge/health")"
assert_eq "direct-to-origin (non-CF source) → 403" "403" "$acode"
# Spoofing the CF header from a non-CF source must NOT bypass the lockdown.
aspoof="$(in_attacker "curl -sk -o /dev/null -w '%{http_code}' -H 'CF-Connecting-IP: 203.0.113.1' https://edge/health")"
assert_eq "spoofed CF-Connecting-IP from non-CF source still → 403" "403" "$aspoof"

echo
echo "── Internal endpoints blocked at the edge ──"
mcode="$(in_cf "curl -sk -o /dev/null -w '%{http_code}' https://edge/metrics")"
assert_eq "/metrics blocked at edge → 403" "403" "$mcode"
mbody="$(in_cf "curl -sk https://edge/metrics")"
assert_not_contains "/metrics body never reaches client" "mock_metric" "$mbody"

echo
echo "── Security headers ──"
hdr="$(in_cf "curl -sk -D - -o /dev/null https://edge/ | tr -d '\r' | tr 'A-Z' 'a-z'")"
assert_contains "HSTS present"                 "strict-transport-security: max-age=63072000" "$hdr"
assert_contains "X-Frame-Options DENY"         "x-frame-options: deny"        "$hdr"
assert_contains "X-Content-Type-Options"       "x-content-type-options: nosniff" "$hdr"
assert_contains "Referrer-Policy"              "referrer-policy: strict-origin" "$hdr"
srv_line="$(printf '%s\n' "$hdr" | grep '^server:' || true)"
assert_not_contains "Server header hides version (server_tokens off)" "/" "$srv_line"

echo
echo "── Rate limiting (expensive endpoint) ──"
# api_expensive zone: 2r/s, burst 5. 20 rapid POSTs must produce some 429s.
codes="$(in_cf 'for i in $(seq 1 20); do curl -sk -o /dev/null -w "%{http_code}\n" -X POST https://edge/api/v1/evaluate; done')"
n429="$(printf '%s\n' "$codes" | grep -c 429 || true)"
n2xx="$(printf '%s\n' "$codes" | grep -c 200 || true)"
if [ "${n429:-0}" -ge 1 ] && [ "${n2xx:-0}" -ge 1 ]; then
    green "rate limit engaged on /api/v1/evaluate (${n2xx}×200, ${n429}×429 of 20)"
else
    red "rate limit not observed (${n2xx}×200, ${n429}×429 of 20)"
fi

echo
echo "════════════════════════════════════════════════════════════════"
printf ' RESULT: \033[32m%d passed\033[0m, %s%d failed\033[0m\n' "$PASS" "$([ "$FAIL" -gt 0 ] && printf '\033[31m' || printf '\033[32m')" "$FAIL"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
