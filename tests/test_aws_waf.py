"""Validate AWS WAF post-launch pack for issue #17."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.issue_helpers import issue_exists

REPO_ROOT = Path(__file__).resolve().parents[1]
WAF_DIR = REPO_ROOT / "infra" / "waf"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "WAF.md"
SCRIPT = REPO_ROOT / "scripts" / "test_waf_edge.py"
DEMO = REPO_ROOT / "reminders" / "DEMO_ISSUE_17.md"

REQUIRED_TF = [
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "locals.tf",
    "waf.tf",
    "outputs.tf",
    "README.md",
    "terraform.tfvars.example",
]


def test_waf_terraform_layout():
    for name in REQUIRED_TF:
        assert (WAF_DIR / name).is_file(), name


def test_web_acl_has_managed_rules_rate_and_association():
    text = (WAF_DIR / "waf.tf").read_text(encoding="utf-8")
    assert "aws_wafv2_web_acl" in text
    assert "AWSManagedRulesCommonRuleSet" in text
    assert "AWSManagedRulesAmazonIpReputationList" in text
    assert "AWSManagedRulesKnownBadInputsRuleSet" in text
    assert "AWSManagedRulesSQLiRuleSet" in text
    assert "rate_based_statement" in text
    assert "aws_wafv2_web_acl_association" in text
    assert "SizeRestrictions_BODY" in text
    assert "enable_blocking" in text


def test_staged_rollout_variable_defaults_to_count_mode():
    text = (WAF_DIR / "variables.tf").read_text(encoding="utf-8")
    assert "enable_blocking" in text
    assert "default     = false" in text or "default = false" in text
    assert "ip_allowlist" in text
    assert "ip_blocklist" in text


def test_runbook_has_exception_process():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "Allow an IP" in text or "allowlist" in text.lower()
    assert "Block an IP" in text or "blocklist" in text.lower()
    assert "Staged rollout" in text or "COUNT" in text
    assert "ALB" in text
    assert "detach" in text.lower() or "Disassociate" in text


def test_issue_backlog_documents_issue_17():
    assert issue_exists(17)


def test_demo_note_exists():
    assert DEMO.is_file()
    assert "#17" in DEMO.read_text(encoding="utf-8")


def test_simulate_script_passes():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--simulate"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
