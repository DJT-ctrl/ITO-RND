#!/usr/bin/env python3
"""Non-prod EC2 idle stop/start + cleanup policy (issue #19).

Reads infra/rightsizing/idle_policy.json. Never targets ito:env=prod.

  python scripts/apply_nonprod_idle_policy.py --action auto --simulate
  python scripts/apply_nonprod_idle_policy.py --action stop --live
  python scripts/apply_nonprod_idle_policy.py --action cleanup --simulate
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "infra" / "rightsizing" / "idle_policy.json"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def desired_action_now(policy: dict, now: datetime | None = None) -> str:
    """Return 'start', 'stop', or 'none' based on UTC schedule."""
    now = now or datetime.now(timezone.utc)
    schedule = policy["schedule_utc"]
    weekday = now.weekday()  # 0=Mon … 6=Sun
    hour = now.hour
    if weekday >= 5 and schedule.get("stop_all_weekend", True):
        return "stop"
    start_h = int(schedule["start_weekdays_at_hour"])
    stop_h = int(schedule["stop_weekdays_after_hour"])
    if start_h <= hour < stop_h:
        return "start"
    return "stop"


def simulate_inventory(policy: dict, action: str) -> dict:
    """Deterministic offline inventory for CI / dry demos."""
    envs = policy["applies_to_envs"]
    instances = [
        {
            "id": "i-dev0001",
            "ito:env": "dev",
            "state": "running",
            "ito:idle-policy": "office-hours",
            "eligible": True,
        },
        {
            "id": "i-stg0001",
            "ito:env": "staging",
            "state": "stopped",
            "ito:idle-policy": "office-hours",
            "eligible": True,
        },
        {
            "id": "i-prd0001",
            "ito:env": "prod",
            "state": "running",
            "ito:idle-policy": "none",
            "eligible": False,
            "reason": "prod never auto-stopped",
        },
    ]
    planned = []
    for inst in instances:
        if not inst["eligible"]:
            continue
        if action == "stop" and inst["state"] == "running":
            planned.append({"id": inst["id"], "op": "stop", "env": inst["ito:env"]})
        if action == "start" and inst["state"] == "stopped":
            planned.append({"id": inst["id"], "op": "start", "env": inst["ito:env"]})

    cleanup = {
        "unattached_eips": [{"allocation_id": "eipalloc-devidle", "env": "dev"}],
        "old_dev_snapshots": [{"snapshot_id": "snap-olddev", "age_days": 21}],
    }
    return {
        "mode": "simulate",
        "action": action,
        "applies_to_envs": envs,
        "never_applies_to_envs": policy["never_applies_to_envs"],
        "instances_considered": instances,
        "planned_instance_ops": planned,
        "cleanup_candidates": cleanup if action == "cleanup" else [],
        "ok": True,
        "prod_protected": True,
    }


def live_ec2_ops(policy: dict, action: str, region: str) -> dict:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("boto3 required for --live") from exc

    ec2 = boto3.client("ec2", region_name=region)
    filters = [
        {"Name": "tag:ito:project", "Values": [policy["required_tags"]["ito:project"]]},
        {"Name": "tag:ito:idle-policy", "Values": [policy["required_tags"]["ito:idle-policy"]]},
        {"Name": "tag:ito:env", "Values": policy["applies_to_envs"]},
    ]
    resp = ec2.describe_instances(Filters=filters)
    planned: list[dict] = []
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
            env = tags.get("ito:env", "")
            if env in policy["never_applies_to_envs"]:
                continue
            state = inst["State"]["Name"]
            iid = inst["InstanceId"]
            if action == "stop" and state == "running":
                planned.append({"id": iid, "op": "stop", "env": env})
            if action == "start" and state == "stopped":
                planned.append({"id": iid, "op": "start", "env": env})

    stop_ids = [p["id"] for p in planned if p["op"] == "stop"]
    start_ids = [p["id"] for p in planned if p["op"] == "start"]
    if stop_ids:
        ec2.stop_instances(InstanceIds=stop_ids)
    if start_ids:
        ec2.start_instances(InstanceIds=start_ids)

    return {
        "mode": "live",
        "action": action,
        "planned_instance_ops": planned,
        "ok": True,
        "prod_protected": True,
    }


def live_cleanup(policy: dict, region: str) -> dict:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("boto3 required for --live") from exc

    ec2 = boto3.client("ec2", region_name=region)
    released: list[str] = []
    # Unattached EIPs tagged for the project (best-effort).
    addresses = ec2.describe_addresses().get("Addresses", [])
    for addr in addresses:
        tags = {t["Key"]: t["Value"] for t in addr.get("Tags", [])}
        if tags.get("ito:project") != policy["required_tags"]["ito:project"]:
            continue
        if tags.get("ito:env") in policy["never_applies_to_envs"]:
            continue
        if "AssociationId" not in addr and tags.get("ito:env") in policy["applies_to_envs"]:
            ec2.release_address(AllocationId=addr["AllocationId"])
            released.append(addr["AllocationId"])

    return {
        "mode": "live",
        "action": "cleanup",
        "released_eips": released,
        "ok": True,
        "note": "Snapshot/volume deletes remain operator-confirmed in v1 — EIP release only when tagged non-prod.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        choices=("auto", "stop", "start", "cleanup"),
        default="auto",
    )
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--region", default="eu-west-2")
    args = parser.parse_args(argv)

    if not args.live:
        args.simulate = True

    policy = load_policy()
    action = args.action
    if action == "auto":
        action = desired_action_now(policy)

    if args.simulate:
        if args.action == "cleanup" or action == "cleanup":
            result = simulate_inventory(policy, "cleanup")
        else:
            result = simulate_inventory(policy, action)
    else:
        if args.action == "cleanup":
            result = live_cleanup(policy, args.region)
        else:
            result = live_ec2_ops(policy, action, args.region)

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
