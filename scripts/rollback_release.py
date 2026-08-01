#!/usr/bin/env python3
"""Rollback the Compose API to the last good git SHA (issue #20).

Reads data/deploy/LAST_GOOD.json written by deploy_release.py, checks out that
ref (or --ref), rebuilds api, and runs smoke checks.

  python scripts/rollback_release.py --dry-run
  python scripts/rollback_release.py
  python scripts/rollback_release.py --ref <explicit-sha>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import deploy_release as deploy  # noqa: E402

LAST_GOOD = REPO_ROOT / "data" / "deploy" / "LAST_GOOD.json"


def load_last_good() -> dict:
    if not LAST_GOOD.is_file():
        raise FileNotFoundError(
            f"missing {LAST_GOOD} — run deploy_release.py once to record a rollback point"
        )
    return json.loads(LAST_GOOD.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="", help="Override LAST_GOOD git SHA")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.ref:
        target = args.ref
        meta = {"git_sha": target, "source": "cli"}
    else:
        meta = load_last_good()
        target = meta["git_sha"]

    print(json.dumps({"action": "rollback", "target": target, "meta": meta}))

    for cmd in (
        ["git", "fetch", "--tags", "--prune", "origin"],
        ["git", "checkout", target],
    ):
        proc = deploy.run(cmd, dry_run=args.dry_run)
        if proc.returncode != 0 and not args.dry_run:
            print(proc.stderr, file=sys.stderr)
            return proc.returncode

    proc = deploy.run(
        ["docker", "compose", "up", "-d", "--build", "--remove-orphans", "api"],
        dry_run=args.dry_run,
    )
    if proc.returncode != 0 and not args.dry_run:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    if not args.dry_run:
        time.sleep(3)
        post = deploy.smoke(args.base_url)
        print(json.dumps({"post_smoke": post}))
        if not post["ok"]:
            print("rollback post-smoke failed — escalate (check #15 restore)", file=sys.stderr)
            return 3

    print(json.dumps({"ok": True, "mode": "dry-run" if args.dry_run else "live", "restored_ref": target}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
