#!/usr/bin/env bash
# Run the whole edge test suite:
#   1. cloudflare-setup.sh against a mock CF API (python3 + curl only)
#   2. the Nginx edge end-to-end in Docker (config validity + routing/security)
# Exits non-zero if either suite fails.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"

rc=0
echo "###############################################################"
echo "# 1/2  Cloudflare setup script"
echo "###############################################################"
"${DIR}/test-cloudflare-setup.sh" || rc=1

echo
echo "###############################################################"
echo "# 2/2  Nginx edge (Docker)"
echo "###############################################################"
"${DIR}/test-edge.sh" || rc=1

echo
if [ "$rc" -eq 0 ]; then
    printf '\033[32m╔══════════════════════════════════╗\n║  ALL EDGE TESTS PASSED           ║\n╚══════════════════════════════════╝\033[0m\n'
else
    printf '\033[31m╔══════════════════════════════════╗\n║  EDGE TESTS FAILED               ║\n╚══════════════════════════════════╝\033[0m\n'
fi
exit "$rc"
