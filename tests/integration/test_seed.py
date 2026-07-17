"""Seed assertions: fixture posts landed with non-null embeddings."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_seeded_posts_present_with_embeddings(db_conn, seed_meta):
    expected_ids = set(seed_meta["post_ids"])
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT post_id, embedding IS NOT NULL AS has_embedding
            FROM posts
            WHERE post_id = ANY(%s)
            ORDER BY post_id
            """,
            (list(expected_ids),),
        )
        rows = cur.fetchall()

    found = {post_id for post_id, _ in rows}
    assert found == expected_ids, f"Missing seeded posts: {expected_ids - found}"
    assert all(has_emb for _, has_emb in rows), "One or more seed embeddings are NULL"
