#!/usr/bin/env python3
"""
Generate reminders/ISSUE_BACKLOG.md from reminders/ISSUES.yaml.
Run from repo root: python scripts/generate_issue_backlog.py
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def generate_backlog_markdown(issues_yaml_path: Path, output_path: Path) -> None:
    """Generate ISSUE_BACKLOG.md from ISSUES.yaml."""
    
    with open(issues_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    issues = data.get("issues", [])
    
    # Build markdown
    lines = [
        "# Issue Backlog — requirements reference",
        "",
        "**Repository (canonical):** [intotheopen/intotheopen-backend](https://github.com/intotheopen/intotheopen-backend)",
        "**Source of truth:** [reminders/ISSUES.yaml](ISSUES.yaml) (this file is auto-generated; do not edit manually)",
        "**Workflow:** [FOR_AI.md](FOR_AI.md) + [GIT_ISSUE_WORKFLOW.md](GIT_ISSUE_WORKFLOW.md) — **one issue → one PR**.",
        "",
        "---",
        "",
    ]
    
    for issue in issues:
        num = issue.get("number")
        title = issue.get("title")
        branch = issue.get("branch")
        docs = issue.get("docs")
        why = issue.get("why")
        scope = issue.get("scope", [])
        acceptance_criteria = issue.get("acceptance_criteria", [])
        execution_notes = issue.get("execution_notes", [])
        
        lines.append(f"## Issue #{num} — requirements ({title})")
        lines.append("")
        lines.append(f"**Issue:** [intotheopen/intotheopen-backend#{num}](https://github.com/intotheopen/intotheopen-backend/issues/{num})")
        lines.append(f"**Branch:** `{branch}`")
        lines.append(f"**Docs:** [`{docs}`](../{docs})")
        lines.append("")
        lines.append("### Why")
        lines.append("")
        lines.append(why)
        lines.append("")
        
        if scope:
            lines.append("### Scope")
            lines.append("")
            for item in scope:
                lines.append(f"- {item}")
            lines.append("")
        
        if acceptance_criteria:
            lines.append("### Acceptance criteria")
            lines.append("")
            lines.append("| Criterion | Deliverable |")
            lines.append("| --------- | ----------- |")
            for criterion in acceptance_criteria:
                c_text = criterion.get("criterion", "")
                d_text = criterion.get("deliverable", "")
                lines.append(f"| {c_text} | {d_text} |")
            lines.append("")
        
        if execution_notes:
            lines.append("### Execution order")
            lines.append("")
            for note in execution_notes:
                lines.append(f"- {note}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # Write output
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated {output_path}")


if __name__ == "__main__":
    repo_root = Path(__file__).parent.parent
    issues_yaml = repo_root / "reminders" / "ISSUES.yaml"
    output_backlog = repo_root / "reminders" / "ISSUE_BACKLOG.md"
    
    if not issues_yaml.exists():
        print(f"ERROR: {issues_yaml} not found", file=sys.stderr)
        sys.exit(1)
    
    generate_backlog_markdown(issues_yaml, output_backlog)
