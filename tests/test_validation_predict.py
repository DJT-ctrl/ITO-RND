"""Tests for validation_pipeline.predict LLM fallback."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic_ai import UnexpectedModelBehavior

from agents.retrieval import RetrievalContext
from api.schemas import SimilarPost
from config.settings import Settings
from validation_pipeline.predict import PredictionOutput, predict_for_post, save_prediction
from validation_pipeline.schemas import CollectedPost, PredictionRecord, PredictionTelemetry


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
        validation_feedback_injection_enabled=False,
        validation_window_hours=48,
    )


def _post() -> CollectedPost:
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
    mock_gather.return_value = RetrievalContext(
        query_embedding=[0.0] * 3072,
        embedding_model_version="models/gemini-embedding-001",
        similar_posts=[],
        global_candidates=[
            SimilarPost(
                post_id="strong-global",
                content="A sufficiently detailed historical LinkedIn post for meaningful comparison context.",
                likes=20,
                comments=4,
                shares=2,
                total_engagement=26,
                engagement_percentile=90.0,
                engagement_zscore=1.0,
                cosine_distance=0.04,
            )
        ],
    )

    result = asyncio.run(predict_for_post(_post(), _settings()))

    assert result.predicted_engagement_percentile == 62.5
    assert result.predicted_total_engagement == 240
    assert "deterministic neighbor weighting" in result.reasoning.lower()
    assert result.telemetry.cross_reference_status == "ready"
    assert result.telemetry.cross_reference_count == 1


@patch("validation_pipeline.predict.insert_prediction")
@patch("validation_pipeline.predict.register_vector")
@patch("validation_pipeline.predict.create_schema")
@patch("validation_pipeline.predict.get_connection")
def test_save_prediction_accepts_backtest_kwargs(
    mock_get_connection,
    _mock_schema,
    _mock_register,
    mock_insert,
):
    conn = MagicMock()
    mock_get_connection.return_value = conn
    due = datetime.now(timezone.utc)
    mock_insert.return_value = PredictionRecord(
        prediction_id="00000000-0000-0000-0000-000000000001",
        linkedin_post_id="7482042397649137666",
        linkedin_url="https://linkedin.com/post/1",
        content="AI marketing trends for 2026.",
        posted_at=due,
        predicted_engagement_percentile=50.0,
        validation_due_at=due,
        is_backtest=True,
        prediction_horizon_hours=72.0,
    )

    prediction = PredictionOutput(
        predicted_engagement_percentile=50.0,
        predicted_total_engagement=100,
        predicted_likes=80,
        predicted_comments=15,
        predicted_shares=5,
        prediction_method="audience_adjusted",
        neighbor_count=8,
        reasoning="test",
        telemetry=PredictionTelemetry(),
    )
    saved = save_prediction(
        _post(),
        prediction,
        _settings(),
        validation_due_at=due,
        is_backtest=True,
        validation_window_hours=72,
    )

    new_pred = mock_insert.call_args.args[1]
    assert new_pred.is_backtest is True
    assert new_pred.prediction_horizon_hours == 72.0
    assert saved.is_backtest is True
    conn.close.assert_called_once()
