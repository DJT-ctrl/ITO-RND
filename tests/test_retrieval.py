"""Tests for the shared ordinary-neighbor and global-candidate retrieval context."""

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np

from agents.retrieval import retrieve_post_context
from config.settings import Settings


def settings() -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        linkedin_cookies=[],
        gemini_api_key="fake-key",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://fake/fake",
    )


def row(post_id: str) -> dict:
    return {
        "post_id": post_id,
        "content": "A sufficiently detailed historical LinkedIn post for meaningful comparison context.",
        "likes": 10,
        "comments": 2,
        "shares": 1,
        "total_engagement": 13,
        "engagement_percentile": 75.0,
        "engagement_zscore": 0.8,
        "cosine_distance": 0.05,
    }


def test_retrieval_embeds_once_and_separates_global_candidates():
    connection = MagicMock()
    with (
        patch("agents.retrieval.embed_query", return_value=(np.zeros(3072, dtype=np.float32), 10)) as embed,
        patch("agents.retrieval.get_connection", return_value=connection),
        patch("agents.retrieval.register_vector"),
        patch("agents.retrieval.find_similar", side_effect=[[row("ordinary")], [row("global")]]) as find,
    ):
        context = asyncio.run(
            retrieve_post_context(
                "Draft post",
                settings(),
                neighbor_limit=10,
                global_candidate_limit=25,
                user_id="subscriber-1",
                prefer_niche="ai_tech",
            )
        )

    assert embed.call_count == 1
    assert [post.post_id for post in context.similar_posts] == ["ordinary"]
    assert [post.post_id for post in context.global_candidates] == ["global"]
    assert context.global_candidate_error is None
    assert find.call_args_list[0].kwargs["user_id"] == "subscriber-1"
    assert find.call_args_list[0].kwargs["limit"] == 10
    assert find.call_args_list[1].kwargs["user_id"] is None
    assert find.call_args_list[1].kwargs["limit"] == 25
    assert connection.close.call_count == 2


def test_global_candidate_failure_does_not_drop_ordinary_neighbors():
    with (
        patch("agents.retrieval.embed_query", return_value=(np.zeros(3072, dtype=np.float32), 10)),
        patch("agents.retrieval.get_connection", return_value=MagicMock()),
        patch("agents.retrieval.register_vector"),
        patch("agents.retrieval.find_similar", side_effect=[[row("ordinary")], RuntimeError("candidate DB unavailable")]),
    ):
        context = asyncio.run(retrieve_post_context("Draft post", settings()))

    assert [post.post_id for post in context.similar_posts] == ["ordinary"]
    assert context.global_candidates == []
    assert context.global_candidate_error == "candidate DB unavailable"
