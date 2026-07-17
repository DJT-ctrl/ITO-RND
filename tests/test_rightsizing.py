"""Validate EC2/EBS rightsizing pack for issue #19."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "infra" / "rightsizing" / "baseline.json"
POLICY = REPO_ROOT / "infra" / "rightsizing" / "idle_policy.json"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "RIGHTSIZING.md"
IDLE_SCRIPT = REPO_ROOT / "scripts" / "apply_nonprod_idle_policy.py"
REVIEW_SCRIPT = REPO_ROOT / "scripts" / "run_rightsizing_review.py"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"
DEMO = REPO_ROOT / "reminders" / "DEMO_ISSUE_19.md"
REVIEW_DIR = REPO_ROOT / "docs" / "ops" / "rightsizing-reviews"


def test_baseline_selected_with_rationale():
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert payload["ec2"]["instance_type"] == "t3.small"
    assert payload["ebs"]["root"]["type"] == "gp3"
    assert payload["ebs"]["data"]["size_gb"] == 50
    assert "rationale" in payload["ec2"]
    assert "rationale" in payload["ebs"]["data"]


def test_idle_policy_protects_prod():
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    assert "prod" in payload["never_applies_to_envs"]
    assert "dev" in payload["applies_to_envs"]
    assert "staging" in payload["applies_to_envs"]
    assert payload["required_tags"]["ito:idle-policy"] == "office-hours"


def test_runbook_covers_baseline_idle_and_monthly_review():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "t3.small" in text
    assert "gp3" in text
    assert "idle" in text.lower()
    assert "Monthly" in text or "monthly" in text
    assert "office-hours" in text


def test_issue_backlog_documents_issue_19():
    text = BACKLOG.read_text(encoding="utf-8")
    assert "Issue #19 — requirements" in text
    assert "rightsizing" in text.lower() or "Rightsizing" in text


def test_demo_note_exists():
    assert DEMO.is_file()
    assert "#19" in DEMO.read_text(encoding="utf-8")


def test_idle_policy_simulate_auto_and_protects_prod():
    proc = subprocess.run(
        [sys.executable, str(IDLE_SCRIPT), "--action", "auto", "--simulate"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["prod_protected"] is True
    assert "prod" in payload["never_applies_to_envs"]
    prod = [i for i in payload["instances_considered"] if i["ito:env"] == "prod"][0]
    assert prod["eligible"] is False


def test_schedule_helper_weekend_stops():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import apply_nonprod_idle_policy as idle

    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    saturday = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)  # Saturday
    assert idle.desired_action_now(policy, saturday) == "stop"
    wednesday_noon = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert idle.desired_action_now(policy, wednesday_noon) == "start"
    wednesday_night = datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc)
    assert idle.desired_action_now(policy, wednesday_night) == "stop"


def test_monthly_review_simulate_writes_artifacts():
    month = "2026-07"
    proc = subprocess.run(
        [
            sys.executable,
            str(REVIEW_SCRIPT),
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
    md = REVIEW_DIR / f"{month}.md"
    js = REVIEW_DIR / f"{month}.json"
    assert md.is_file()
    assert js.is_file()
    text = md.read_text(encoding="utf-8")
    assert "Rightsizing review" in text
    assert "Checklist" in text
    assert "t3.small" in text
