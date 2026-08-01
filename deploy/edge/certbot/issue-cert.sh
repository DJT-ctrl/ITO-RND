#!/bin/sh
# Issue / renew the origin TLS certificate from Let's Encrypt using the
# DNS-01 challenge via the Cloudflare API — the "automated HTTPS validation"
# in the Definition of Done.
#
# Why DNS-01 (not HTTP-01) here: the hostname is proxied through Cloudflare
# (orange cloud), so a Let's Encrypt HTTP-01 validator hitting the domain would
# be answered by Cloudflare's edge, not this origin. DNS-01 proves control by
# creating a TXT record through the Cloudflare API instead, so it works fully
# automatically even while the origin sits behind the proxy and is locked down
# to Cloudflare-only. It also supports wildcard certs.
#
# POSIX sh (no bashisms): the compose `certbot` service runs it under the
# Alpine image's busybox /bin/sh, and it also runs fine on a host with certbot
# + python3-certbot-dns-cloudflare installed.
#
# Environment:
#   CF_API_TOKEN       token with Zone:DNS:Edit on the zone (Zone:Read too).
#   EDGE_DOMAIN        hostname to certify, e.g. api.example.com.
#   LETSENCRYPT_EMAIL  contact for expiry notices.
#   CERTBOT_STAGING    "true" → LE staging CA (untrusted, high rate limits) for
#                      dry runs. Default "false".
#   LIVE_CERT_DIR      where to publish fullchain.pem/privkey.pem for Nginx
#                      (default deploy/edge/certs). certbot keeps its own copies
#                      under /etc/letsencrypt.
set -eu

: "${CF_API_TOKEN:?set CF_API_TOKEN (Zone:DNS:Edit)}"
: "${EDGE_DOMAIN:?set EDGE_DOMAIN (e.g. api.example.com)}"
: "${LETSENCRYPT_EMAIL:?set LETSENCRYPT_EMAIL}"
CERTBOT_STAGING="${CERTBOT_STAGING:-false}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIVE_CERT_DIR="${LIVE_CERT_DIR:-${SCRIPT_DIR}/../certs}"

if ! command -v certbot >/dev/null 2>&1; then
    echo "certbot not found. Run inside the compose 'certbot' service:" >&2
    echo "  docker compose -f docker-compose.yml -f deploy/edge/docker-compose.edge.yml \\" >&2
    echo "    run --rm certbot" >&2
    echo "or install: apt-get install certbot python3-certbot-dns-cloudflare" >&2
    exit 1
fi

# Cloudflare credentials file for the plugin. 0600 — it holds the API token.
umask 077
CREDS="$(mktemp)"
trap 'rm -f "$CREDS"' EXIT
printf 'dns_cloudflare_api_token = %s\n' "$CF_API_TOKEN" > "$CREDS"

STAGING_FLAG=""
if [ "$CERTBOT_STAGING" = "true" ]; then
    STAGING_FLAG="--staging"
    echo "→ Using Let's Encrypt STAGING (certs will be untrusted)."
fi

echo "→ Requesting cert for ${EDGE_DOMAIN} via Cloudflare DNS-01…"
# shellcheck disable=SC2086  # STAGING_FLAG is intentionally word-split (may be empty)
certbot certonly \
    --non-interactive --agree-tos \
    --email "$LETSENCRYPT_EMAIL" \
    --dns-cloudflare \
    --dns-cloudflare-credentials "$CREDS" \
    --dns-cloudflare-propagation-seconds 30 \
    --key-type ecdsa \
    --cert-name "$EDGE_DOMAIN" \
    -d "$EDGE_DOMAIN" \
    $STAGING_FLAG

LE_DIR="/etc/letsencrypt/live/${EDGE_DOMAIN}"
echo "→ Publishing cert to ${LIVE_CERT_DIR} for Nginx…"
mkdir -p "$LIVE_CERT_DIR"
cp -L "${LE_DIR}/fullchain.pem" "${LIVE_CERT_DIR}/fullchain.pem"
cp -L "${LE_DIR}/privkey.pem"   "${LIVE_CERT_DIR}/privkey.pem"
chmod 600 "${LIVE_CERT_DIR}/privkey.pem"

echo "✓ Certificate ready for ${EDGE_DOMAIN}."
echo "  Reload Nginx to apply:  docker exec ito-edge nginx -s reload"
echo "  Renewal: certbot renews automatically; re-run this to re-publish."
