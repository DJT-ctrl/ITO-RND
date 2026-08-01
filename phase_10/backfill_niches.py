"""Backfill ``posts.niche`` from free-text ``topic`` (T10.6).

Usage:
    python -m phase_10.backfill_niches
"""

from __future__ import annotations

import logging

from config.settings import load_settings
from phase_10.topics import NICHES, normalize_topic_to_niche
from storage.vector_store import create_schema, get_connection

logger = logging.getLogger(__name__)


def backfill_niches(*, limit: int | None = None) -> int:
    """Set ``niche`` from ``topic`` where niche is null/blank. Returns rows updated."""
    settings = load_settings()
    conn = get_connection(settings)
    try:
        create_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT post_id, topic
                FROM posts
                WHERE niche IS NULL OR BTRIM(niche) = ''
                ORDER BY inserted_at
                """
                + (" LIMIT %s" if limit is not None else ""),
                (limit,) if limit is not None else None,
            )
            rows = cur.fetchall()

            updated = 0
            for post_id, topic in rows:
                niche = normalize_topic_to_niche(topic)
                if niche not in NICHES:
                    niche = "other"
                cur.execute(
                    "UPDATE posts SET niche = %s WHERE post_id = %s",
                    (niche, post_id),
                )
                updated += cur.rowcount
            conn.commit()
        return updated
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    count = backfill_niches()
    logger.info("Backfilled niche on %s post(s)", count)
    print(f"Backfilled niche on {count} post(s)")


if __name__ == "__main__":
    main()
