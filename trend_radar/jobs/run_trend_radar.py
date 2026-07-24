"""CLI: weekly corpus trend radar / topic-drift job."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from config.settings import load_settings
from trend_radar.batch import run_trend_radar_batch


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline A2 job: cluster clean corpus embeddings for a week and "
            "write growth signals to the trends table."
        )
    )
    parser.add_argument(
        "--week",
        type=str,
        default=None,
        help="Week start date YYYY-MM-DD (Monday preferred; coerced to Monday)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Cluster in memory only; do not write or call label LLM",
    )
    parser.add_argument(
        "--skip-llm-labels",
        action="store_true",
        help="Use keyword/topic fallback labels only",
    )
    args = parser.parse_args()

    week: date | None = None
    if args.week:
        week = date.fromisoformat(args.week)

    settings = load_settings()
    try:
        batch = run_trend_radar_batch(
            settings,
            week=week,
            dry_run=args.dry_run,
            skip_llm_labels=args.skip_llm_labels or args.dry_run,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: week_start={batch.week_start} posts={batch.posts_in_window} "
        f"clusters={batch.clusters_written} dry_run={batch.dry_run}"
    )
    for note in batch.notes:
        print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
