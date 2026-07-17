#!/usr/bin/env python3
"""Validate HTTPS ingress hardening artifacts for issue #14.

  python scripts/test_ingress_hardening.py --simulate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = REPO_ROOT / "infra" / "ingress" / "sg_allowlist.json"
NGINX = REPO_ROOT / "deploy" / "nginx" / "ito-api.conf"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "INGRESS_HTTPS.md"
INSTALL = REPO_ROOT / "deploy" / "nginx" / "install-tls.sh"


def simulate() -> dict:
    errors: list[str] = []
    if not ALLOWLIST.is_file():
        errors.append("missing sg_allowlist.json")
        payload = {}
    else:
        payload = json.loads(ALLOWLIST.read_text(encoding="utf-8"))

    if payload.get("public_ingress_tcp") != [80, 443]:
        errors.append("public_ingress_tcp must be [80, 443]")
    forbidden = set(payload.get("forbidden_public_tcp") or [])
    for port in (8000, 5432):
        if port not in forbidden:
            errors.append(f"forbidden_public_tcp must include {port}")

    waf = payload.get("waf") or {}
    if waf.get("status") != "deferred":
        errors.append("waf.status must be deferred for MVP")
    if waf.get("follow_up_issue") != 17:
        errors.append("waf.follow_up_issue must be 17")

    nginx = NGINX.read_text(encoding="utf-8") if NGINX.is_file() else ""
    if "listen 443" not in nginx:
        errors.append("ito-api.conf must listen 443")
    if "return 301 https://" not in nginx:
        errors.append("ito-api.conf must redirect HTTP to HTTPS")
    if "127.0.0.1:8000" not in nginx:
        errors.append("ito-api.conf must proxy to 127.0.0.1:8000")

    runbook = RUNBOOK.read_text(encoding="utf-8") if RUNBOOK.is_file() else ""
    for needle in ("HTTPS", "#17", "certbot", "security group"):
        if needle == "security group":
            if "security group" not in runbook.lower():
                errors.append("runbook missing: security group")
        elif needle not in runbook:
            errors.append(f"runbook missing: {needle}")
    if "deferred" not in runbook.lower() and "Defer" not in runbook:
        errors.append("runbook missing: WAF deferred")

    if not INSTALL.is_file():
        errors.append("missing install-tls.sh")

    return {
        "mode": "simulate",
        "ok": not errors,
        "errors": errors,
        "allowlist": payload,
        "files": {
            "sg_allowlist.json": ALLOWLIST.is_file(),
            "ito-api.conf": NGINX.is_file(),
            "INGRESS_HTTPS.md": RUNBOOK.is_file(),
            "install-tls.sh": INSTALL.is_file(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", default=True)
    args = parser.parse_args(argv)
    _ = args  # simulate-only for MVP CI
    result = simulate()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
