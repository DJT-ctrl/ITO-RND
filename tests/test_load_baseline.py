"""Validate load-baseline scripts and docs exist (issue #21)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LOAD_DIR = REPO_ROOT / "scripts" / "load"
SCENARIOS = LOAD_DIR / "scenarios.yaml"
RUNNER = LOAD_DIR / "run_load_test.py"
STUB = LOAD_DIR / "stub_api.py"
BASELINE_DOC = REPO_ROOT / "docs" / "ops" / "LOAD_BASELINE.md"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"

REQUIRED_SCENARIOS = {"smoke", "similar-posts-steady", "evaluate-mixed", "baseline"}


def test_load_scripts_and_docs_exist():
    assert RUNNER.is_file()
    assert STUB.is_file()
    assert SCENARIOS.is_file()
    assert BASELINE_DOC.is_file()
    assert BACKLOG.is_file()


def test_issue_backlog_documents_issue_21_requirements():
    text = BACKLOG.read_text(encoding="utf-8")
    assert "#21" in text or "issues/21" in text
    assert "Issue #21 — requirements" in text
    assert "Reproducible load test scripts" in text
    assert "Baseline performance report" in text
    assert "Improvement plan" in text


def test_baseline_doc_covers_acceptance_and_targets():
    text = BASELINE_DOC.read_text(encoding="utf-8")
    assert "Top 3 bottlenecks" in text
    assert "Next-release targets" in text
    assert "similar-posts" in text
    assert "evaluate" in text
    assert "#22" in text
    assert "≤ 1.0s" in text or "<= 1.0s" in text
    assert "≤ 20s" in text or "<= 20s" in text


def test_scenarios_yaml_lists_required_routes():
    payload = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    assert REQUIRED_SCENARIOS <= set(payload["scenarios"])
    baseline = payload["scenarios"]["baseline"]
    paths = {block["path"] for block in baseline["requests"]}
    assert "/health" in paths
    assert "/api/v1/similar-posts" in paths
    assert "/api/v1/evaluate" in paths


def test_smoke_against_stub_api():
    """End-to-end: stub server + smoke scenario (no Gemini/DB)."""
    proc = subprocess.Popen(
        [sys.executable, str(STUB), "--port", "8011"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                response = httpx.get("http://127.0.0.1:8011/health", timeout=0.5)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("stub_api did not become ready on :8011")

        completed = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--scenario",
                "smoke",
                "--base-url",
                "http://127.0.0.1:8011",
            ],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        report = json.loads(completed.stdout)
        assert report["scenario"] == "smoke"
        assert len(report["routes"]) == 3
        assert all(route["errors"] == 0 for route in report["routes"])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
