#!/usr/bin/env python3
"""Generate a monthly AWS cloud cost report for issue #18.

Live mode uses Cost Explorer (ce:GetCostAndUsage). Simulate mode writes a
reviewable report from the documented MVP budget split (no AWS calls) so CI
and local runs always work.

  python scripts/generate_monthly_cost_report.py --month 2026-07 --simulate
  python scripts/generate_monthly_cost_report.py --month 2026-07
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_ROOT / "docs" / "ops" / "cost-reports"
PLAYBOOK = REPO_ROOT / "docs" / "ops" / "COST_CONTROLS.md"

# Defaults aligned with infra/budgets variables.
DEFAULT_SPLIT = {
    "overall": 80.0,
    "Amazon Elastic Compute Cloud - Compute": 45.0,
    "Amazon Elastic Block Store": 15.0,
    "Amazon CloudWatch": 12.0,
    "Other": 8.0,
}


def parse_month(value: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        raise argparse.ArgumentTypeError("month must be YYYY-MM")
    year, month = map(int, value.split("-"))
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def simulate_breakdown(month_label: str) -> dict:
    # Deterministic sample under the overall budget for reviewable demos.
    seed = sum(ord(c) for c in month_label)
    services = {
        "Amazon Elastic Compute Cloud - Compute": round(38.0 + (seed % 5), 2),
        "Amazon Elastic Block Store": round(9.5 + (seed % 3) * 0.5, 2),
        "Amazon CloudWatch": round(4.0 + (seed % 4) * 0.25, 2),
        "AWS Secrets Manager": 1.2,
        "Amazon Simple Notification Service": 0.15,
        "Tax": 0.0,
    }
    total = round(sum(services.values()), 2)
    return {
        "mode": "simulate",
        "month": month_label,
        "currency": "USD",
        "total": total,
        "by_service": services,
        "budget_overall": DEFAULT_SPLIT["overall"],
        "budget_split": DEFAULT_SPLIT,
        "within_budget": total <= DEFAULT_SPLIT["overall"],
    }


def fetch_cost_explorer(start: date, end: date, region: str) -> dict:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("boto3 required for live reports: pip install boto3") from exc

    client = boto3.client("ce", region_name="us-east-1")  # CE API is global/us-east-1
    response = client.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    by_service: dict[str, float] = {}
    total = 0.0
    for result in response.get("ResultsByTime", []):
        for group in result.get("Groups", []):
            name = group["Keys"][0]
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            by_service[name] = round(by_service.get(name, 0.0) + amount, 2)
            total += amount
    month_label = start.strftime("%Y-%m")
    return {
        "mode": "live",
        "month": month_label,
        "currency": "USD",
        "total": round(total, 2),
        "by_service": dict(sorted(by_service.items(), key=lambda kv: (-kv[1], kv[0]))),
        "budget_overall": DEFAULT_SPLIT["overall"],
        "budget_split": DEFAULT_SPLIT,
        "within_budget": total <= DEFAULT_SPLIT["overall"],
        "ce_region_note": region,
    }


def render_markdown(payload: dict, reviewed_by: str) -> str:
    lines = [
        f"# Cloud cost report — {payload['month']}",
        "",
        f"- Generated: `{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}`",
        f"- Mode: `{payload['mode']}`",
        f"- Total unblended: **${payload['total']:.2f} {payload['currency']}**",
        f"- Overall budget: **${payload['budget_overall']:.2f}**",
        f"- Within budget: **{'yes' if payload['within_budget'] else 'NO'}**",
        f"- Playbook: [`COST_CONTROLS.md`](../COST_CONTROLS.md)",
        "",
        "## By service",
        "",
        "| Service | USD |",
        "| ------- | --- |",
    ]
    for name, amount in payload["by_service"].items():
        if amount == 0:
            continue
        lines.append(f"| {name} | {amount:.2f} |")
    lines.extend(
        [
            "",
            "## Budget split (targets)",
            "",
            "| Bucket | USD |",
            "| ------ | --- |",
        ]
    )
    for name, amount in payload["budget_split"].items():
        lines.append(f"| {name} | {amount:.2f} |")
    lines.extend(
        [
            "",
            "## Review",
            "",
            f"- Reviewed by: {reviewed_by or '_pending_'}",
            "- Actions taken: _pending_",
            "- Follow-ups: _pending_",
            "",
            "Use the checklist in `COST_CONTROLS.md` → Monthly cloud cost report.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(payload: dict, reviewed_by: str) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    month = payload["month"]
    md_path = REPORT_DIR / f"{month}.md"
    json_path = REPORT_DIR / f"{month}.json"
    md_path.write_text(render_markdown(payload, reviewed_by), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month",
        type=str,
        default=(date.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
        help="Month to report (YYYY-MM). Default: previous calendar month.",
    )
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--reviewed-by", default="")
    args = parser.parse_args(argv)

    start, end = parse_month(args.month)
    month_label = start.strftime("%Y-%m")

    if not PLAYBOOK.is_file():
        raise SystemExit(f"missing playbook: {PLAYBOOK}")

    if args.simulate:
        payload = simulate_breakdown(month_label)
    else:
        payload = fetch_cost_explorer(start, end, args.region)

    md_path, json_path = write_report(payload, args.reviewed_by)
    print(json.dumps({"ok": True, "markdown": str(md_path), "json": str(json_path), **payload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
