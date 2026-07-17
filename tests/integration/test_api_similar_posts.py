"""similar-posts journey: API ↔ DB ↔ pgvector with stubbed embed_query."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_similar_posts_returns_seeded_neighbor(http_client, seed_meta):
    response = http_client.post(
        "/api/v1/similar-posts",
        json={"content": seed_meta["query_text"], "limit": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query_content"] == seed_meta["query_text"]
    results = body["results"]
    assert len(results) >= 1, "Expected at least one neighbor from seed data"

    top = results[0]
    assert top["post_id"] == seed_meta["expected_top_post_id"], (
        f"Expected top hit {seed_meta['expected_top_post_id']!r}, got {top['post_id']!r} "
        f"(full order: {[r['post_id'] for r in results]})"
    )
    assert "cosine_distance" in top
    assert top["cosine_distance"] == pytest.approx(0.0, abs=1e-4)
