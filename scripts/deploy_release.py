#!/usr/bin/env python3
"""Controlled single-instance deploy for issue #20.

Pre-smoke → record LAST_GOOD → optional git checkout → compose rebuild api →
post-smoke. Use --dry-run to print the plan without mutating.

  python scripts/deploy_release.py --ref main --dry-run
  python scripts/deploy_release.py --ref <sha-or-tag>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAST_GOOD = REPO_ROOT / "data" / "deploy" / "LAST_GOOD.json"


def run(cmd: list[str], *, dry_run: bool, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, cwd=str(cwd), check=False, capture_output=True, text=True)


def http_status(url: str, method: str = "GET", body: bytes | None = None, timeout: float = 10.0) -> int:
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError):
        return 0


def smoke(base_url: str) -> dict:
    health = http_status(f"{base_url.rstrip('/')}/health")
    similar = http_status(
        f"{base_url.rstrip('/')}/api/v1/similar-posts",
        method="POST",
        body=b'{"content":"deploy smoke"}',
        timeout=30.0,
    )
    ok = health == 200 and similar != 0 and similar < 500
    return {"ok": ok, "health_status": health, "similar_posts_status": similar}


def git_sha() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def api_image_id(dry_run: bool) -> str:
    proc = run(
        ["docker", "compose", "images", "-q", "api"],
        dry_run=dry_run,
    )
    if dry_run:
        return "dry-run"
    return (proc.stdout or "").strip().splitlines()[0] if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def write_last_good(sha: str, image: str) -> None:
    LAST_GOOD.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "git_sha": sha,
        "api_image_id": image,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    LAST_GOOD.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="", help="Git tag/SHA to deploy (optional if already checked out)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-git", action="store_true", help="Do not fetch/checkout; only rebuild")
    parser.add_argument("--migrate", action="store_true", help="Run compose migrate after API rebuild")
    args = parser.parse_args(argv)

    print("== pre-deploy smoke ==")
    pre = smoke(args.base_url)
    print(json.dumps(pre))
    if not pre["ok"] and not args.dry_run:
        print("pre-smoke failed — abort deploy", file=sys.stderr)
        return 2

    prev_sha = git_sha()
    prev_image = api_image_id(args.dry_run)
    print(f"recording LAST_GOOD sha={prev_sha} image={prev_image}")
    if not args.dry_run:
        write_last_good(prev_sha, prev_image)

    if args.ref and not args.skip_git:
        print(f"== git sync → {args.ref} ==")
        for cmd in (
            ["git", "fetch", "--tags", "--prune", "origin"],
            ["git", "checkout", args.ref],
        ):
            proc = run(cmd, dry_run=args.dry_run)
            if proc.returncode != 0 and not args.dry_run:
                print(proc.stderr, file=sys.stderr)
                return proc.returncode

    print("== rolling restart api ==")
    proc = run(
        ["docker", "compose", "up", "-d", "--build", "--remove-orphans", "api"],
        dry_run=args.dry_run,
    )
    if proc.returncode != 0 and not args.dry_run:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    if args.migrate:
        proc = run(["docker", "compose", "run", "--rm", "migrate"], dry_run=args.dry_run)
        if proc.returncode != 0 and not args.dry_run:
            print(proc.stderr, file=sys.stderr)
            return proc.returncode

    if not args.dry_run:
        # Give the API a moment to bind.
        time.sleep(3)

    print("== post-deploy smoke ==")
    post = smoke(args.base_url) if not args.dry_run else {"ok": True, "health_status": 200, "similar_posts_status": 200, "dry_run": True}
    print(json.dumps(post))
    if not post["ok"]:
        print("post-smoke failed — run: python scripts/rollback_release.py", file=sys.stderr)
        return 3

    print(json.dumps({"ok": True, "mode": "dry-run" if args.dry_run else "live", "ref": args.ref or prev_sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
