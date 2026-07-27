#!/usr/bin/env bash
# Install + configure Amazon CloudWatch Agent on the Compose host (issue #16).
set -euo pipefail

ENVIRONMENT="${1:-dev}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_JSON="${REPO_ROOT}/deploy/cloudwatch/amazon-cloudwatch-agent.json"
DEST_DIR="/opt/aws/amazon-cloudwatch-agent/etc"
DEST_JSON="${DEST_DIR}/amazon-cloudwatch-agent.json"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0 ${ENVIRONMENT}" >&2
  exit 1
fi

if ! command -v amazon-cloudwatch-agent-ctl >/dev/null 2>&1; then
  echo "Installing Amazon CloudWatch Agent…"
  dnf install -y amazon-cloudwatch-agent || yum install -y amazon-cloudwatch-agent
fi

mkdir -p "${DEST_DIR}" /opt/ito-rnd/data/logs/api
# Substitute {{environment}} placeholder from the checked-in template.
sed "s/{{environment}}/${ENVIRONMENT}/g" "${SRC_JSON}" > "${DEST_JSON}"

amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c "file:${DEST_JSON}" \
  -s

amazon-cloudwatch-agent-ctl -a status -m ec2 || true
echo "CloudWatch agent configured for environment=${ENVIRONMENT}"
echo "Log groups: /ito/${ENVIRONMENT}/{api,host,docker}"
