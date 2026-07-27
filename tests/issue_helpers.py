"""Utilities for reading issue requirements from ISSUES.yaml."""

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML required; install with: pip install pyyaml")


def load_issues() -> dict[int, dict[str, Any]]:
    """Load all issues from reminders/ISSUES.yaml, keyed by issue number."""
    # issue_helpers.py is in tests/, so parent is the repo root
    repo_root = Path(__file__).resolve().parent.parent
    issues_yaml = repo_root / "reminders" / "ISSUES.yaml"
    
    if not issues_yaml.exists():
        raise FileNotFoundError(f"ISSUES.yaml not found at {issues_yaml}")
    
    with open(issues_yaml, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    issues = {}
    for issue in data.get("issues", []):
        num = issue.get("number")
        if num:
            issues[num] = issue
    
    return issues


def get_issue(issue_number: int) -> dict[str, Any] | None:
    """Get a specific issue by number, or None if not found."""
    issues = load_issues()
    return issues.get(issue_number)


def issue_exists(issue_number: int) -> bool:
    """Check if an issue is documented in ISSUES.yaml."""
    return get_issue(issue_number) is not None
