"""Validate AWS runtime ADR artifacts (issue #11)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADR = REPO_ROOT / "docs" / "ops" / "ADR-001-aws-runtime.md"
BACKLOG = REPO_ROOT / "reminders" / "ISSUE_BACKLOG.md"
DEPLOY_README = REPO_ROOT / "deploy" / "README.md"
ROOT_README = REPO_ROOT / "README.md"


def test_adr_exists_and_accepts_ec2_compose():
    assert ADR.is_file()
    text = ADR.read_text(encoding="utf-8")
    assert "ADR-001" in text
    assert "Accepted" in text
    assert "EC2" in text
    assert "Docker Compose" in text or "Compose" in text
    assert "ECS" in text  # deferred alternative documented
    assert "Rollback" in text or "rollback" in text
    assert "Security assumptions" in text
    assert "Trust boundaries" in text or "trust boundaries" in text
    assert "RPO" in text or "#15" in text


def test_adr_documents_deploy_and_owners():
    text = ADR.read_text(encoding="utf-8")
    assert "Deployment path" in text
    assert "Operational owner" in text or "owner model" in text.lower()
    assert "#12" in text
    assert "#20" in text


def test_issue_backlog_documents_issue_11():
    assert BACKLOG.is_file()
    text = BACKLOG.read_text(encoding="utf-8")
    assert "Issue #11 — requirements" in text
    assert "EC2" in text
    assert "ADR" in text


def test_readmes_link_adr():
    assert "ADR-001" in DEPLOY_README.read_text(encoding="utf-8")
    assert "ADR-001" in ROOT_README.read_text(encoding="utf-8") or "aws-runtime" in ROOT_README.read_text(
        encoding="utf-8"
    )
