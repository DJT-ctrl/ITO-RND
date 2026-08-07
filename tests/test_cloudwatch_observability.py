"""Validate CloudWatch observability pack for issue #16."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OBS = REPO_ROOT / "infra" / "observability"
DEPLOY_CW = REPO_ROOT / "deploy" / "cloudwatch"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "CLOUDWATCH.md"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"
PUBLISH = REPO_ROOT / "scripts" / "publish_cw_api_metrics.py"
TEST_ALARMS = REPO_ROOT / "scripts" / "test_cloudwatch_alarms.py"
DEMO = REPO_ROOT / "reminders" / "DEMO_ISSUE_16.md"

REQUIRED_TF = [
    "versions.tf",
    "providers.tf",
    "variables.tf",
    "locals.tf",
    "logs.tf",
    "sns.tf",
    "alarms.tf",
    "dashboard.tf",
    "iam.tf",
    "outputs.tf",
    "README.md",
]


def test_observability_terraform_files_exist():
    assert (OBS / "README.md").is_file()
    for name in REQUIRED_TF:
        assert (OBS / name).is_file(), name


def test_log_groups_have_retention():
    text = (OBS / "logs.tf").read_text(encoding="utf-8")
    assert "aws_cloudwatch_log_group" in text
    assert "retention_in_days" in text
    assert "/ito/" in (OBS / "locals.tf").read_text(encoding="utf-8")


def test_essential_alarms_defined():
    text = (OBS / "alarms.tf").read_text(encoding="utf-8")
    for needle in (
        "StatusCheckFailed",
        "disk_used_percent",
        "ErrorRate",
        "LatencyP95Seconds",
        "Api5xxLogCount",
        "aws_sns_topic.critical",
    ):
        assert needle in text, needle


def test_sns_supports_email_and_https_destinations():
    text = (OBS / "sns.tf").read_text(encoding="utf-8")
    assert 'protocol  = "email"' in text or 'protocol = "email"' in text
    assert 'protocol  = "https"' in text or 'protocol = "https"' in text


def test_dashboard_covers_api_and_host_health():
    text = (OBS / "dashboard.tf").read_text(encoding="utf-8")
    assert "ErrorRate" in text
    assert "LatencyP95Seconds" in text
    assert "StatusCheckFailed" in text
    assert "disk_used_percent" in text


def test_agent_config_and_install_script_exist():
    agent = DEPLOY_CW / "amazon-cloudwatch-agent.json"
    install = DEPLOY_CW / "install-agent.sh"
    assert agent.is_file()
    assert install.is_file()
    payload = json.loads(agent.read_text(encoding="utf-8"))
    assert "logs" in payload and "metrics" in payload
    assert "disk" in payload["metrics"]["metrics_collected"]
    assert "used_percent" in payload["metrics"]["metrics_collected"]["disk"]["measurement"]
    assert "fetch-config" in install.read_text(encoding="utf-8")


def test_runbook_links_each_alarm_to_mitigation():
    text = RUNBOOK.read_text(encoding="utf-8")
    for section in (
        "host-status-check-failed",
        "disk-used-percent",
        "api-error-rate",
        "api-latency-p95",
        "api-5xx-log-spike",
    ):
        assert section in text, section
    assert "Diagnosis" in text
    assert "Mitigation" in text
    assert "Controlled test" in text
    assert "14 days" in text or "retention" in text.lower()


def test_issue_backlog_documents_issue_16_requirements():
    text = BACKLOG.read_text(encoding="utf-8")
    assert "Issue #16 — requirements" in text
    assert "CloudWatch" in text
    assert "Critical alerts fire" in text or "controlled test" in text.lower()


def test_demo_note_exists():
    assert DEMO.is_file()
    assert "#16" in DEMO.read_text(encoding="utf-8")


def test_controlled_alarm_simulate_passes():
    proc = subprocess.run(
        [sys.executable, str(TEST_ALARMS), "--simulate"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "simulate"


def test_publish_script_dry_run_against_synthetic_metrics(tmp_path):
    """Unit-level: parser helpers via --dry-run with a tiny HTTP stub."""
    # Exercise module import + argparse dry path without network by calling
    # internal parsers directly.
    import importlib.util

    spec = importlib.util.spec_from_file_location("publish_cw", PUBLISH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sample = """
# HELP http_requests_total Total
# TYPE http_requests_total counter
http_requests_total{handler="/api/v1/similar-posts",status="200"} 95
http_requests_total{handler="/api/v1/similar-posts",status="500"} 5
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{le="1.0"} 80
http_request_duration_seconds_bucket{le="30.0"} 98
http_request_duration_seconds_bucket{le="+Inf"} 100
"""
    series = mod._parse_prometheus(sample)
    assert mod._error_rate(series) == 5.0
    assert mod._histogram_p95(series) >= 1.0
