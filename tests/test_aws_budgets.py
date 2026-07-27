"""Validate AWS budget alerts / cost controls pack for issue #18."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.issue_helpers import issue_exists

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGETS = REPO_ROOT / "infra" / "budgets"
PLAYBOOK = REPO_ROOT / "docs" / "ops" / "COST_CONTROLS.md"
REPORT_SCRIPT = REPO_ROOT / "scripts" / "generate_monthly_cost_report.py"
DEMO = REPO_ROOT / "reminders" / "DEMO_ISSUE_18.md"
REPORT_DIR = REPO_ROOT / "docs" / "ops" / "cost-reports"

REQUIRED_TF = [
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "locals.tf",
    "sns.tf",
    "budgets.tf",
    "outputs.tf",
    "README.md",
    "terraform.tfvars.example",
]


def test_budgets_terraform_layout():
    for name in REQUIRED_TF:
        assert (BUDGETS / name).is_file(), name


def test_overall_and_service_budgets_with_forecast():
    text = (BUDGETS / "budgets.tf").read_text(encoding="utf-8")
    assert "aws_budgets_budget" in text
    assert "monthly_overall" in text
    assert "monthly_ec2" in text
    assert "monthly_ebs" in text
    assert "monthly_cloudwatch" in text
    assert 'notification_type         = "ACTUAL"' in text or 'notification_type          = "ACTUAL"' in text
    assert "FORECASTED" in text
    assert "Amazon Elastic Compute Cloud - Compute" in text
    assert "Amazon Elastic Block Store" in text
    assert "Amazon CloudWatch" in text


def test_sns_allows_budgets_service_principal():
    text = (BUDGETS / "sns.tf").read_text(encoding="utf-8")
    assert "budgets.amazonaws.com" in text
    assert "SNS:Publish" in text or "sns:Publish" in text
    assert 'protocol  = "email"' in text or 'protocol = "email"' in text
    assert 'protocol  = "https"' in text or 'protocol = "https"' in text


def test_default_monthly_split_documented():
    readme = (BUDGETS / "README.md").read_text(encoding="utf-8")
    playbook = PLAYBOOK.read_text(encoding="utf-8")
    for doc in (readme, playbook):
        assert "80" in doc
        assert "45" in doc
        assert "15" in doc
        assert "12" in doc


def test_playbook_has_response_and_report_steps():
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert "Response playbook" in text
    assert "Cost Explorer" in text or "cost report" in text.lower()
    assert "Rightsizing" in text or "rightsizing" in text
    assert "FORECASTED" in text or "forecast" in text.lower()
    assert "50%" in text and "80%" in text


def test_issue_backlog_documents_issue_18():
    assert issue_exists(18)


def test_demo_note_exists():
    assert DEMO.is_file()
    assert "#18" in DEMO.read_text(encoding="utf-8")


def test_simulate_monthly_report_writes_artifacts():
    month = "2026-06"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPORT_SCRIPT),
            "--month",
            month,
            "--simulate",
            "--reviewed-by",
            "ci",
        ],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "simulate"
    md = REPORT_DIR / f"{month}.md"
    js = REPORT_DIR / f"{month}.json"
    assert md.is_file()
    assert js.is_file()
    text = md.read_text(encoding="utf-8")
    assert f"Cloud cost report — {month}" in text
    assert "By service" in text
    assert "Review" in text
    assert "Within budget" in text
