"""Validate single-instance deploy/rollback runbook for issue #20."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.issue_helpers import issue_exists

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "ops" / "DEPLOY_ROLLBACK.md"
DRILL = REPO_ROOT / "docs" / "ops" / "DEPLOY_DRILL_LATEST.json"
DEPLOY = REPO_ROOT / "scripts" / "deploy_release.py"
ROLLBACK = REPO_ROOT / "scripts" / "rollback_release.py"
DRILL_SCRIPT = REPO_ROOT / "scripts" / "run_deploy_drill.py"
DEMO = REPO_ROOT / "reminders" / "DEMO_ISSUE_20.md"
STACK_UNIT = REPO_ROOT / "deploy" / "ito-stack.service"


def test_runbook_and_scripts_exist():
    assert RUNBOOK.is_file()
    assert DEPLOY.is_file()
    assert ROLLBACK.is_file()
    assert DRILL_SCRIPT.is_file()
    assert STACK_UNIT.is_file()


def test_runbook_covers_strategy_smoke_rollback_downtime():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "controlled rolling restart" in text
    assert "Downtime window" in text
    assert "≤ 10 minutes" in text or "<= 10 minutes" in text
    assert "Pre-deploy" in text
    assert "Post-deploy" in text
    assert "Rollback" in text
    assert "decision" in text.lower() or "Trigger" in text
    assert "deploy_release.py" in text
    assert "rollback_release.py" in text


def test_issue_backlog_documents_issue_20():
    assert issue_exists(20)


def test_demo_note_exists():
    assert DEMO.is_file()
    assert "#20" in DEMO.read_text(encoding="utf-8")


def test_deploy_dry_run_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(DEPLOY), "--dry-run", "--skip-git", "--ref", "HEAD"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "pre-deploy smoke" in proc.stdout


def test_rollback_dry_run_with_explicit_ref():
    proc = subprocess.run(
        [sys.executable, str(ROLLBACK), "--dry-run", "--ref", "HEAD"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "rollback" in proc.stdout


def test_simulate_drill_writes_report():
    proc = subprocess.run(
        [sys.executable, str(DRILL_SCRIPT), "--simulate"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["within_downtime_budget"] is True
    assert DRILL.is_file()
    saved = json.loads(DRILL.read_text(encoding="utf-8"))
    assert saved["mode"] == "simulate"
    assert saved["ok"] is True
