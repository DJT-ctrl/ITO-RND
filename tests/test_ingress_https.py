"""Validate HTTPS ingress hardening for issue #14."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.issue_helpers import issue_exists

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = REPO_ROOT / "infra" / "ingress" / "sg_allowlist.json"
NGINX = REPO_ROOT / "deploy" / "nginx" / "ito-api.conf"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "INGRESS_HTTPS.md"
INSTALL = REPO_ROOT / "deploy" / "nginx" / "install-tls.sh"
SCRIPT = REPO_ROOT / "scripts" / "test_ingress_hardening.py"
DEMO = REPO_ROOT / "reminders" / "DEMO_ISSUE_14.md"
LEGACY = REPO_ROOT / "deploy" / "nginx.conf.example"


def test_allowlist_policy():
    payload = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    assert payload["public_ingress_tcp"] == [80, 443]
    assert 8000 in payload["forbidden_public_tcp"]
    assert 5432 in payload["forbidden_public_tcp"]
    assert payload["waf"]["status"] == "deferred"
    assert payload["waf"]["follow_up_issue"] == 17
    assert payload["tls"]["http_behavior"] == "redirect_to_https"
    assert payload["upstream"]["api"] == "127.0.0.1:8000"


def test_nginx_tls_and_redirect():
    text = NGINX.read_text(encoding="utf-8")
    assert "listen 443" in text
    assert "return 301 https://" in text
    assert "127.0.0.1:8000" in text
    assert "ssl_certificate" in text
    assert INSTALL.is_file()
    assert "certbot" in INSTALL.read_text(encoding="utf-8")


def test_legacy_example_redirects_not_cleartext_api():
    text = LEGACY.read_text(encoding="utf-8")
    assert "return 301 https://" in text
    assert "proxy_pass http://127.0.0.1:8000" not in text


def test_runbook_documents_https_sg_and_waf_deferral():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "HTTPS" in text
    assert "security group" in text.lower() or "Security group" in text
    assert "#17" in text
    assert "defer" in text.lower() or "Deferred" in text
    assert "certbot" in text.lower() or "Let's Encrypt" in text


def test_issue_backlog_documents_issue_14():
    assert issue_exists(14)


def test_demo_note_exists():
    assert DEMO.is_file()
    assert "#14" in DEMO.read_text(encoding="utf-8")


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
