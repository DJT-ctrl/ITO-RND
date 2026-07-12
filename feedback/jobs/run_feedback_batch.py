"""CLI: backfill template feedback for validated predictions."""

from __future__ import annotations

import argparse
import sys

from config.settings import load_settings
from feedback.batch import run_feedback_batch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate template feedback for validated predictions missing v1 rows."
    )
    parser.add_argument("--limit", type=int, default=100, help="Max predictions to process")
    args = parser.parse_args()

    settings = load_settings()
    try:
        batch = run_feedback_batch(settings, limit=args.limit)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: processed={batch.processed} generated={batch.generated} "
        f"failed={batch.failed} skipped={batch.skipped}"
    )
    return 0 if batch.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
