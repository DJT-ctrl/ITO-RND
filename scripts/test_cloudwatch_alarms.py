#!/usr/bin/env python3
"""Controlled CloudWatch alarm test for issue #16.

Default mode is --simulate (no AWS calls): validates alarm naming + runbook
anchors and prints the operator procedure.

Live mode sets an alarm to ALARM then OK so SNS/Slack/PagerDuty destinations
receive a controlled notification:

  python scripts/test_cloudwatch_alarms.py --simulate
  python scripts/test_cloudwatch_alarms.py --alarm intotheopen-dev-api-error-rate --live
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "docs" / "ops" / "CLOUDWATCH.md"
ALARMS_TF = REPO_ROOT / "infra" / "observability" / "alarms.tf"

ESSENTIAL_ALARM_SUFFIXES = (
    "host-status-check-failed",
    "disk-used-percent",
    "api-error-rate",
    "api-latency-p95",
    "api-5xx-log-spike",
)

RUNBOOK_ANCHORS = (
    "host-status-check-failed",
    "disk-used-percent",
    "api-error-rate",
    "api-latency-p95",
    "api-5xx-log-spike",
)


def simulate() -> dict:
    alarms_text = ALARMS_TF.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    missing_tf = [s for s in ESSENTIAL_ALARM_SUFFIXES if s not in alarms_text]
    missing_rb = [a for a in RUNBOOK_ANCHORS if f"#{a}" not in runbook and a not in runbook]
    procedure = [
        "1. Confirm SNS subscription is Confirmed (email link or HTTPS).",
        "2. Pick a critical alarm, e.g. <project>-<env>-api-error-rate.",
        "3. aws cloudwatch set-alarm-state --state-value ALARM "
        "--state-reason 'issue #16 controlled test' --alarm-name <name>",
        "4. Verify notification arrives (email / Slack / PagerDuty).",
        "5. aws cloudwatch set-alarm-state --state-value OK "
        "--state-reason 'issue #16 controlled test clear' --alarm-name <name>",
        "6. Record result in the go-live checklist (#27).",
    ]
    return {
        "mode": "simulate",
        "ok": not missing_tf and not missing_rb,
        "missing_alarm_suffixes_in_tf": missing_tf,
        "missing_runbook_anchors": missing_rb,
        "procedure": procedure,
        "runbook": str(RUNBOOK.relative_to(REPO_ROOT)),
    }


def set_alarm_state(alarm_name: str, state: str, reason: str, region: str) -> None:
    import boto3

    client = boto3.client("cloudwatch", region_name=region)
    client.set_alarm_state(
        AlarmName=alarm_name,
        StateValue=state,
        StateReason=reason,
    )


def live(alarm_name: str, region: str, hold_seconds: int) -> dict:
    set_alarm_state(
        alarm_name,
        "ALARM",
        "issue #16 controlled test — expect SNS notification",
        region,
    )
    time.sleep(max(hold_seconds, 1))
    set_alarm_state(
        alarm_name,
        "OK",
        "issue #16 controlled test clear",
        region,
    )
    return {
        "mode": "live",
        "ok": True,
        "alarm_name": alarm_name,
        "states": ["ALARM", "OK"],
        "note": "Confirm SNS/Slack/PagerDuty received the ALARM notification.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate", action="store_true", default=False)
    parser.add_argument("--live", action="store_true", default=False)
    parser.add_argument("--alarm", default="", help="Alarm name for --live")
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--hold-seconds", type=int, default=15)
    args = parser.parse_args(argv)

    if not args.live:
        args.simulate = True

    if args.live:
        if not args.alarm:
            print("--alarm is required with --live", file=sys.stderr)
            return 2
        result = live(args.alarm, args.region, args.hold_seconds)
    else:
        result = simulate()

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
