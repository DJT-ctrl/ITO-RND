"""CLI: refresh template cluster roll-up summaries (Phase I.2)."""

from __future__ import annotations

import argparse
import sys

from config.settings import load_settings
from feedback.store import refresh_cluster_stats
from feedback.summarize import refresh_cluster_rollups
from storage.vector_store import create_schema, get_connection


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute cluster stats (optional) and write rollup_summary text "
            "for injection formats rollup_top2 / rollup_contrastive."
        )
    )
    parser.add_argument(
        "--skip-stats",
        action="store_true",
        help="Only rewrite rollup_summary from existing cluster stats",
    )
    args = parser.parse_args()

    settings = load_settings()
    if not settings.database_url:
        print("Error: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    conn = get_connection(settings)
    try:
        create_schema(conn)
        if not args.skip_stats:
            n_stats = refresh_cluster_stats(
                conn,
                age_aware_enabled=settings.validation_age_aware_enabled,
            )
            print(f"Refreshed cluster stats for {n_stats} clusters")
        n_rollups = refresh_cluster_rollups(conn)
        print(f"Wrote rollup_summary for {n_rollups} clusters")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
