"""evaluate journey: HTTP → stubbed evaluate → real DB neighbors."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_evaluate_returns_canned_predictor_and_neighbors(http_client, seed_meta):
    response = http_client.post(
        "/api/v1/evaluate",
        json={"content": seed_meta["query_text"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["draft_content"] == seed_meta["query_text"]
    assert body["predictor_result"] is not None
    assert "engagement_percentile" in body["predictor_result"]

    similar = body["similar_posts"]
    assert isinstance(similar, list)
    assert len(similar) >= 1
    assert similar[0]["post_id"] == seed_meta["expected_top_post_id"]
