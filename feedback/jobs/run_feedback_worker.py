"""CLI: process async feedback_jobs queue (Phase I.1)."""

from __future__ import annotations

import argparse
import sys

from config.settings import load_settings
from feedback.batch import run_feedback_worker


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Claim pending feedback_jobs and generate template (+ optional hybrid) "
            "feedback. Run after validations enqueue jobs."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max jobs to claim this run (default 20)",
    )
    args = parser.parse_args()

    settings = load_settings()
    try:
        result = run_feedback_worker(settings, limit=args.limit)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: claimed={result.claimed} succeeded={result.succeeded} "
        f"failed={result.failed} dead_lettered={result.dead_lettered}"
    )
    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
