#!/usr/bin/env python3
"""Monthly EC2/EBS rightsizing review report (issue #19).

  python scripts/run_rightsizing_review.py --month 2026-07 --simulate
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "infra" / "rightsizing" / "baseline.json"
POLICY = REPO_ROOT / "infra" / "rightsizing" / "idle_policy.json"
RUNBOOK = REPO_ROOT / "docs" / "ops" / "RIGHTSIZING.md"
OUT_DIR = REPO_ROOT / "docs" / "ops" / "rightsizing-reviews"


def parse_month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("month must be YYYY-MM")
    return value


def simulate_payload(month: str) -> dict:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    return {
        "mode": "simulate",
        "month": month,
        "baseline": baseline,
        "idle_policy_envs": policy["applies_to_envs"],
        "findings": [
            {
                "resource": "i-sim-compose",
                "type": baseline["ec2"]["instance_type"],
                "env": "prod",
                "verdict": "keep",
                "note": "Matches baseline t3.small",
            },
            {
                "resource": "vol-sim-data",
                "type": f"{baseline['ebs']['data']['size_gb']}G {baseline['ebs']['data']['type']}",
                "env": "prod",
                "verdict": "keep",
                "note": "Under 70% — no grow",
            },
            {
                "resource": "eipalloc-idle",
                "type": "eip",
                "env": "dev",
                "verdict": "cleanup",
                "note": "Unattached non-prod EIP candidate",
            },
        ],
        "checklist": [
            "Compare instance types vs baseline",
            "Review CPU/mem/disk signals",
            "Confirm non-prod idle stops",
            "List unattached EIPs / orphan volumes",
            "Record keep/resize/stop/cleanup decisions",
            "Cross-check #18 EC2/EBS budget slices",
        ],
        "ok": True,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def render_markdown(payload: dict, reviewed_by: str) -> str:
    lines = [
        f"# Rightsizing review — {payload['month']}",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Mode: `{payload['mode']}`",
        f"- Baseline EC2: `{payload['baseline']['ec2']['instance_type']}`",
        f"- Baseline EBS data: `{payload['baseline']['ebs']['data']['size_gb']}G "
        f"{payload['baseline']['ebs']['data']['type']}`",
        f"- Reviewed by: {reviewed_by or '_pending_'}",
        f"- Runbook: [`RIGHTSIZING.md`](../RIGHTSIZING.md)",
        "",
        "## Findings",
        "",
        "| Resource | Type | Env | Verdict | Note |",
        "| -------- | ---- | --- | ------- | ---- |",
    ]
    for row in payload["findings"]:
        lines.append(
            f"| {row['resource']} | {row['type']} | {row['env']} | {row['verdict']} | {row['note']} |"
        )
    lines.extend(["", "## Checklist", ""])
    for item in payload["checklist"]:
        lines.append(f"- [ ] {item}")
    lines.extend(["", "## Decisions", "", "- _pending_", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month",
        type=parse_month,
        default=date.today().strftime("%Y-%m"),
    )
    parser.add_argument("--simulate", action="store_true", default=True)
    parser.add_argument("--reviewed-by", default="")
    args = parser.parse_args(argv)

    if not RUNBOOK.is_file():
        raise SystemExit(f"missing runbook: {RUNBOOK}")

    payload = simulate_payload(args.month)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = OUT_DIR / f"{args.month}.md"
    js = OUT_DIR / f"{args.month}.json"
    md.write_text(render_markdown(payload, args.reviewed_by), encoding="utf-8")
    js.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "markdown": str(md), "json": str(js), **payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
