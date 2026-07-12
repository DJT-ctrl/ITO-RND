"""CLI: process due prediction validations."""

from __future__ import annotations

import argparse
import sys

from config.settings import load_settings
from validation_pipeline.worker import run_due_validations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-scrape and score predictions past their validation window."
    )
    parser.add_argument("--limit", type=int, default=50, help="Max predictions to process")
    args = parser.parse_args()

    settings = load_settings()
    try:
        batch = run_due_validations(settings, limit=args.limit)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: processed={batch.processed} validated={batch.validated} failed={batch.failed}"
    )
    for item in batch.results:
        if item.status == "validated" and item.scores:
            print(
                f"  {item.prediction_id}: delta={item.scores.prediction_delta:+.1f} "
                f"accuracy={item.scores.accuracy_score:.1f}"
            )
        elif item.status == "failed":
            print(f"  {item.prediction_id}: FAILED — {item.error}", file=sys.stderr)
    return 0 if batch.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
