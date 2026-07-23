"""CLI: generate anomaly post-mortems for flagged posts."""

from __future__ import annotations

import argparse
import sys

from config.settings import load_settings
from post_mortems.batch import DEFAULT_LIMIT, run_post_mortem_batch


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline A1 job: LLM post-mortems for posts with "
            "engagement_anomaly_flag = TRUE."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max flagged posts to process (default {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible count only; do not call the LLM or write rows",
    )
    args = parser.parse_args()

    settings = load_settings()
    try:
        batch = run_post_mortem_batch(
            settings,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mode = "dry_run" if args.dry_run else "write"
    print(
        f"Done ({mode}): processed={batch.processed} generated={batch.generated} "
        f"failed={batch.failed} skipped={batch.skipped}"
    )
    for err in batch.errors[:10]:
        print(f"  - {err}", file=sys.stderr)
    return 0 if batch.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
