"""Tests for validation_pipeline.predict LLM fallback."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from pydantic_ai import UnexpectedModelBehavior

from config.settings import Settings
from validation_pipeline.predict import predict_for_post
from validation_pipeline.schemas import CollectedPost


def _settings() -> Settings:
    return Settings(
        apify_api_token="",
        apify_actor_id="",
        apify_profile_actor_id="",
        apify_post_url_actor_id="harvestapi/linkedin-profile-posts",
        linkedin_cookies=[],
        gemini_api_key="fake-key",
        raw_data_dir="data/raw",
        default_search_limit=20,
        database_url="postgresql://fake/fake",
        validation_calibration_enabled=False,
    )


def _post() -> CollectedPost:
    from datetime import datetime, timezone

    return CollectedPost(
        linkedin_post_id="7482042397649137666",
        linkedin_url="https://linkedin.com/post/1",
        author_public_id="author",
        content="AI marketing trends for 2026.",
        posted_at=datetime.now(timezone.utc),
        follower_count=5000,
    )


@patch("validation_pipeline.predict.build_predictor_agent")
@patch("validation_pipeline.predict._gather_similar_posts", new_callable=AsyncMock)
@patch("validation_pipeline.predict.compute_neighbor_prediction")
def test_predict_for_post_falls_back_on_malformed_gemini_response(
    mock_neighbor_prediction,
    mock_gather,
    mock_build_agent,
):
    mock_neighbor_prediction.return_value = {
        "percentile": 62.5,
        "total_engagement_estimate": 240,
        "predicted_likes": 180,
        "predicted_comments": 40,
        "predicted_shares": 20,
        "method": "audience_adjusted",
        "neighbor_count": 10,
        "coverage": 8,
    }
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=UnexpectedModelBehavior("Content field missing from Gemini response"))
    mock_build_agent.return_value = agent

    result = asyncio.run(predict_for_post(_post(), _settings()))

    assert result.predicted_engagement_percentile == 62.5
    assert result.predicted_total_engagement == 240
    assert "deterministic neighbor weighting" in result.reasoning.lower()
