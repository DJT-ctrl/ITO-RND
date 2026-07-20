#!/usr/bin/env bash
# Configure the free Cloudflare proxy in front of the ITO origin — idempotent,
# API-driven, safe to re-run. This is the "Configure free Cloudflare proxy
# routing" half of the task; the Nginx side is the origin it points at.
#
# What it does (all via the Cloudflare API v4, free-plan features only):
#   1. Verifies the API token and resolves the zone name.
#   2. Upserts a PROXIED (orange-cloud) A record  EDGE_DOMAIN → ORIGIN_IP,
#      so all traffic for the hostname routes through Cloudflare's edge.
#   3. Sets SSL/TLS mode to "Full (strict)" — Cloudflare validates the origin
#      certificate, closing the "Flexible = plaintext to origin" hole.
#   4. Turns on Always Use HTTPS, Automatic HTTPS Rewrites, TLS 1.3, and a
#      minimum TLS version of 1.2 — the automated HTTPS behaviour at the edge.
#   5. Enables HSTS at the edge (belt-and-braces with the origin's HSTS header).
#
# Config comes from the environment (see .env.example → the CF_* / EDGE_* keys):
#   CF_API_TOKEN   Cloudflare API token with Zone:DNS:Edit + Zone:Settings:Edit
#                  (scoped to the one zone — never a Global API Key).
#   CF_ZONE_ID     the zone (domain) ID from the Cloudflare dashboard overview.
#   EDGE_DOMAIN    public hostname to serve, e.g. api.example.com.
#   ORIGIN_IP      the origin server's public IPv4 (the EC2 elastic IP).
#   CF_RECORD_PROXIED  optional, default "true" (orange cloud). "false" = grey.
#
# Usage:
#   set -a; source .env; set +a
#   deploy/edge/cloudflare/cloudflare-setup.sh
set -euo pipefail

# Overridable base URL — normally the real API; can point at a mock/staging
# endpoint for testing (see tests/).
API="${CF_API_BASE:-https://api.cloudflare.com/client/v4}"

: "${CF_API_TOKEN:?set CF_API_TOKEN (scoped token, not the Global key)}"
: "${CF_ZONE_ID:?set CF_ZONE_ID (zone ID from the CF dashboard)}"
: "${EDGE_DOMAIN:?set EDGE_DOMAIN (e.g. api.example.com)}"
: "${ORIGIN_IP:?set ORIGIN_IP (origin public IPv4)}"
CF_RECORD_PROXIED="${CF_RECORD_PROXIED:-true}"

# All API calls go through here: bearer auth, JSON, and a hard fail on any
# response whose top-level "success" is not true (Cloudflare always returns
# that envelope). Prints the parsed result to stdout for the caller.
cf() {
    local method="$1" path="$2" body="${3:-}"
    local resp
    if [[ -n "$body" ]]; then
        resp="$(curl -fsS -X "$method" "${API}${path}" \
            -H "Authorization: Bearer ${CF_API_TOKEN}" \
            -H "Content-Type: application/json" \
            --data "$body")"
    else
        resp="$(curl -fsS -X "$method" "${API}${path}" \
            -H "Authorization: Bearer ${CF_API_TOKEN}" \
            -H "Content-Type: application/json")"
    fi
    # Validate the envelope and surface CF errors clearly (python3 is always
    # present in this repo's toolchain; avoids a hard jq dependency).
    printf '%s' "$resp" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if not d.get("success", False):
    errs = "; ".join("%s: %s" % (e.get("code"), e.get("message")) for e in d.get("errors", []))
    sys.stderr.write("Cloudflare API error: " + (errs or json.dumps(d)) + "\n")
    sys.exit(1)
json.dump(d, sys.stdout)
'
}

# Extract one field from a JSON blob on stdin (dotted path, list index ok).
# Missing keys / out-of-range indices → blank line (never crashes), so callers
# can test "is this empty?" — e.g. "does a DNS record already exist?".
jget() {
    python3 -c '
import json, sys
d = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    if isinstance(d, list):
        i = int(k)
        d = d[i] if -len(d) <= i < len(d) else None
    elif isinstance(d, dict):
        d = d.get(k)
    else:
        d = None
    if d is None:
        print(""); sys.exit(0)
print(d)
' "$1"
}

echo "→ Verifying token and zone…"
ZONE_JSON="$(cf GET "/zones/${CF_ZONE_ID}")"
ZONE_NAME="$(printf '%s' "$ZONE_JSON" | jget result.name)"
echo "  zone: ${ZONE_NAME} (${CF_ZONE_ID})"

# --- 1. Upsert the proxied A record ----------------------------------------
echo "→ Upserting A record ${EDGE_DOMAIN} → ${ORIGIN_IP} (proxied=${CF_RECORD_PROXIED})…"
RECORD_BODY="$(python3 -c '
import json, sys
print(json.dumps({
    "type": "A",
    "name": sys.argv[1],
    "content": sys.argv[2],
    "ttl": 1,                       # 1 = "automatic" (required when proxied)
    "proxied": sys.argv[3] == "true",
}))' "$EDGE_DOMAIN" "$ORIGIN_IP" "$CF_RECORD_PROXIED")"

EXISTING="$(cf GET "/zones/${CF_ZONE_ID}/dns_records?type=A&name=${EDGE_DOMAIN}")"
RECORD_ID="$(printf '%s' "$EXISTING" | jget result.0.id)"

if [[ -n "$RECORD_ID" ]]; then
    cf PUT "/zones/${CF_ZONE_ID}/dns_records/${RECORD_ID}" "$RECORD_BODY" >/dev/null
    echo "  updated existing record ${RECORD_ID}"
else
    cf POST "/zones/${CF_ZONE_ID}/dns_records" "$RECORD_BODY" >/dev/null
    echo "  created new record"
fi

# --- 2-5. Zone settings ----------------------------------------------------
set_setting() {
    local name="$1" value="$2"
    echo "→ ${name} = ${value}"
    cf PATCH "/zones/${CF_ZONE_ID}/settings/${name}" "{\"value\":${value}}" >/dev/null
}

set_setting ssl '"strict"'                 # Full (strict): validate origin cert
set_setting always_use_https '"on"'        # edge redirects http→https
set_setting automatic_https_rewrites '"on"'
set_setting min_tls_version '"1.2"'
set_setting tls_1_3 '"on"'

echo "→ security_header (HSTS) = 2y, includeSubDomains, preload"
cf PATCH "/zones/${CF_ZONE_ID}/settings/security_header" '{
  "value": {
    "strict_transport_security": {
      "enabled": true,
      "max_age": 63072000,
      "include_subdomains": true,
      "preload": true,
      "nosniff": true
    }
  }
}' >/dev/null

cat <<EOF

✓ Cloudflare proxy configured for ${EDGE_DOMAIN}
    • Proxied A record → ${ORIGIN_IP} (orange cloud, WAF + DDoS shield active)
    • SSL/TLS mode: Full (strict)
    • Always Use HTTPS + Automatic HTTPS Rewrites + TLS 1.3 + min TLS 1.2
    • Edge HSTS enabled

Next:
  1. Issue an origin certificate so Full (strict) validates:
       deploy/edge/certbot/issue-cert.sh            (Let's Encrypt, DNS-01)
     or a 15-year Cloudflare Origin CA cert (see README).
  2. Lock the origin's security group to Cloudflare IP ranges + your SSH IP.
  3. Bring up the edge:  docker compose -f docker-compose.yml \\
       -f deploy/edge/docker-compose.edge.yml up -d
EOF
