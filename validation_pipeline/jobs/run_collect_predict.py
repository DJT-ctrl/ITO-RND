"""CLI: scrape posts, run predictions, and schedule validation."""

from __future__ import annotations

import argparse
import sys

from config.settings import load_settings
from validation_pipeline.pipeline import run_collect_and_predict_sync


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape LinkedIn posts, predict engagement, and schedule 48h validation."
    )
    parser.add_argument("--search", required=True, help="Search query for LinkedIn post scraper")
    parser.add_argument(
        "--max-posts",
        type=int,
        default=None,
        help="Maximum posts to scrape (defaults to VALIDATION_MAX_POSTS_PER_RUN)",
    )
    parser.add_argument(
        "--profile-limit",
        type=int,
        default=None,
        help="Cap personal profile scrapes per run",
    )
    args = parser.parse_args()

    settings = load_settings()
    max_posts = args.max_posts if args.max_posts is not None else settings.validation_max_posts_per_run
    search_params = {
        "searchQueries": [args.search],
        "maxPosts": max_posts,
        "sortBy": "date",
        "postedLimit": "week",
    }

    def progress(msg: str) -> None:
        print(msg, flush=True)

    try:
        result = run_collect_and_predict_sync(
            search_params,
            settings=settings,
            profile_url_limit=args.profile_limit,
            on_progress=progress,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"Done: scraped={result.scraped} predicted={result.predicted} "
        f"skipped={result.skipped} errors={len(result.errors)}"
    )
    for err in result.errors:
        print(f"  - {err}", file=sys.stderr)
    return 0 if not result.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
