#!/usr/bin/env python3
"""Validate AWS WAF edge pack for issue #17 (simulate / offline).

  python scripts/test_waf_edge.py --simulate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WAF_TF = REPO_ROOT / "infra" / "waf" / "waf.tf"
VARS = REPO_ROOT / "infra" / "waf" / "variables.tf"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "WAF.md"
README = REPO_ROOT / "infra" / "waf" / "README.md"

REQUIRED_MANAGED = (
    "AWSManagedRulesAmazonIpReputationList",
    "AWSManagedRulesCommonRuleSet",
    "AWSManagedRulesKnownBadInputsRuleSet",
    "AWSManagedRulesSQLiRuleSet",
    "RateLimitPerIp",
)


def simulate() -> dict:
    errors: list[str] = []
    waf = WAF_TF.read_text(encoding="utf-8") if WAF_TF.is_file() else ""
    variables = VARS.read_text(encoding="utf-8") if VARS.is_file() else ""
    runbook = RUNBOOK.read_text(encoding="utf-8") if RUNBOOK.is_file() else ""

    if "aws_wafv2_web_acl" not in waf:
        errors.append("missing aws_wafv2_web_acl")
    if "aws_wafv2_web_acl_association" not in waf:
        errors.append("missing web_acl_association")
    for name in REQUIRED_MANAGED:
        if name not in waf:
            errors.append(f"missing rule {name}")
    if "enable_blocking" not in variables:
        errors.append("missing enable_blocking variable")
    if "ip_allowlist" not in variables or "ip_blocklist" not in variables:
        errors.append("missing ip allow/block list variables")
    if "SizeRestrictions_BODY" not in waf:
        errors.append("missing SizeRestrictions_BODY count override")

    for needle in (
        "exception",
        "allowlist",
        "blocklist",
        "COUNT",
        "ALB",
        "enable_blocking",
    ):
        if needle.lower() not in runbook.lower() and needle not in runbook:
            errors.append(f"runbook missing: {needle}")

    if not README.is_file():
        errors.append("missing infra/waf/README.md")

    return {
        "mode": "simulate",
        "ok": not errors,
        "errors": errors,
        "required_managed_rules": list(REQUIRED_MANAGED),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", default=True)
    args = parser.parse_args(argv)
    _ = args
    result = simulate()
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
