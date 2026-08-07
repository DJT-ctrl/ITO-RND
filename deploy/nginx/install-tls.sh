#!/usr/bin/env bash
# Issue #14 — bootstrap HTTP, issue Let's Encrypt cert, install HTTPS+redirect config.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

if [[ -z "${DOMAIN}" || -z "${EMAIL}" ]]; then
  echo "Usage: sudo bash deploy/nginx/install-tls.sh <domain> <email>" >&2
  exit 2
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0 ${DOMAIN} ${EMAIL}" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FINAL_SRC="${SCRIPT_DIR}/ito-api.conf"
CONF_DST="/etc/nginx/conf.d/ito-api.conf"
WEBROOT="/var/www/certbot"
BOOTSTRAP="/etc/nginx/conf.d/ito-api-bootstrap.conf"

dnf install -y nginx certbot 2>/dev/null || yum install -y nginx certbot

mkdir -p "${WEBROOT}"

# 1) HTTP-only bootstrap for ACME (no ssl_certificate paths yet).
cat > "${BOOTSTRAP}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ {
        root ${WEBROOT};
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
rm -f "${CONF_DST}"
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# 2) Issue / renew certificate via webroot.
certbot certonly --webroot \
  -w "${WEBROOT}" \
  -d "${DOMAIN}" \
  --non-interactive \
  --agree-tos \
  -m "${EMAIL}" \
  --keep-until-expiring

# 3) Install final HTTPS + redirect config.
rm -f "${BOOTSTRAP}"
sed "s/api.example.com/${DOMAIN}/g" "${FINAL_SRC}" > "${CONF_DST}"
nginx -t
systemctl reload nginx

echo "TLS enabled for https://${DOMAIN}/ — HTTP should 301 to HTTPS."
echo "Confirm SG allows 80/443 only; API stays on 127.0.0.1:8000 (docs/ops/INGRESS_HTTPS.md)."
