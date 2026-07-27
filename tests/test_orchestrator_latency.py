"""Validate orchestrator latency docs and settings (issue #22)."""

from pathlib import Path

from config.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "ops" / "ORCHESTRATOR_LATENCY.md"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"


def test_orchestrator_latency_doc_exists():
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")
    assert "Latency profile by stage" in text
    assert "Timeout / fallback policy" in text
    assert "AGENT_STEP_TIMEOUT_S" in text
    assert "FINALIZE_TIMEOUT_S" in text
    assert "#21" in text


def test_issue_backlog_documents_issue_22():
    text = BACKLOG.read_text(encoding="utf-8")
    assert "Issue #22 — requirements" in text
    assert "Timeout/fallback policy" in text


def test_default_timeout_settings_loaded():
    settings = load_settings()
    assert settings.agent_step_timeouts_enabled is True
    assert settings.agent_step_timeout_s == 12.0
    assert settings.finalize_timeout_s == 8.0
