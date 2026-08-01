#!/usr/bin/env bash
# Generate a self-signed origin certificate so the Nginx edge can start (and be
# tested) with TLS *before* a real certificate exists.
#
# Two legitimate uses:
#   • Local testing (the edge test harness uses exactly this).
#   • Production bootstrap — Nginx needs *some* cert to start listening on 443;
#     issue-cert.sh then replaces it with a Let's Encrypt cert and reloads.
#
# NOT for production traffic on its own: a self-signed origin cert only works
# with Cloudflare SSL mode "Full" (not "Full (strict)"), because strict mode
# validates the origin chain. Use issue-cert.sh (Let's Encrypt) or a Cloudflare
# Origin CA cert for a strict-mode origin.
#
# Usage:
#   deploy/edge/certbot/gen-selfsigned.sh [OUT_DIR] [CN]
#     OUT_DIR  where fullchain.pem + privkey.pem land (default deploy/edge/certs)
#     CN       certificate common name / SAN (default localhost)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-${SCRIPT_DIR}/../certs}"
CN="${2:-localhost}"

mkdir -p "$OUT_DIR"

if [[ -f "${OUT_DIR}/fullchain.pem" && -f "${OUT_DIR}/privkey.pem" ]]; then
    echo "✓ Cert already present in ${OUT_DIR} — leaving it in place."
    echo "  (delete it first if you want to regenerate.)"
    exit 0
fi

echo "→ Generating self-signed cert for CN=${CN} in ${OUT_DIR}…"
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "${OUT_DIR}/privkey.pem" \
    -out    "${OUT_DIR}/fullchain.pem" \
    -subj   "/CN=${CN}" \
    -addext "subjectAltName=DNS:${CN},DNS:localhost,IP:127.0.0.1"

chmod 600 "${OUT_DIR}/privkey.pem"
echo "✓ Wrote ${OUT_DIR}/fullchain.pem and privkey.pem (valid 365 days)."
