"""Tests for validation_pipeline.worker with mocked dependencies."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from validation_pipeline.schemas import EngagementActuals, PredictionRecord, ValidationScores
from validation_pipeline.worker import run_due_validations


def _due_prediction() -> PredictionRecord:
    now = datetime.now(timezone.utc)
    return PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        author_public_id="author",
        content="test post",
        posted_at=now,
        predicted_engagement_percentile=60.0,
        validation_due_at=now,
    )


@patch("validation_pipeline.worker.try_store_feedback_after_validation")
@patch("validation_pipeline.worker.mark_failed")
@patch("validation_pipeline.worker.mark_validated")
@patch("validation_pipeline.worker.insert_snapshot")
@patch("validation_pipeline.worker.mark_validating")
@patch("validation_pipeline.worker.fetch_engagement_by_urls")
@patch("validation_pipeline.worker.compute_validation_scores")
@patch("validation_pipeline.worker.fetch_corpus_engagement_totals")
@patch("validation_pipeline.worker.fetch_due_predictions")
@patch("validation_pipeline.worker.get_connection")
@patch("validation_pipeline.worker.create_schema")
@patch("validation_pipeline.worker.register_vector")
def test_run_due_validations_success(
    mock_register,
    mock_create_schema,
    mock_get_connection,
    mock_fetch_due,
    mock_corpus,
    mock_scores,
    mock_fetch_by_urls,
    mock_mark_validating,
    mock_insert_snapshot,
    mock_mark_validated,
    mock_mark_failed,
    mock_feedback,
):
    settings = MagicMock()
    settings.database_url = "postgresql://test"
    prediction = _due_prediction()
    mock_get_connection.return_value = MagicMock()
    mock_fetch_due.return_value = [prediction]
    mock_corpus.return_value = [10, 20, 30]
    actuals = EngagementActuals(likes=1, comments=1, shares=1, total_engagement=3)
    mock_fetch_by_urls.return_value = {prediction.prediction_id: actuals}
    scores = ValidationScores(
        actual_engagement_percentile=55.0,
        prediction_delta=-5.0,
        accuracy_score=95.0,
        corpus_sample_size=3,
        likes_delta=-2.0,
        comments_delta=1.0,
        shares_delta=0.0,
        total_engagement_delta=-1.0,
    )
    mock_scores.return_value = scores

    batch = run_due_validations(settings, limit=10)

    assert batch.processed == 1
    assert batch.validated == 1
    assert batch.failed == 0
    mock_mark_validated.assert_called_once()
    mock_insert_snapshot.assert_called_once()
    mock_mark_failed.assert_not_called()
    mock_feedback.assert_called_once_with(prediction, scores, settings)

@patch("validation_pipeline.worker.mark_failed")
@patch("validation_pipeline.worker.mark_validated")
@patch("validation_pipeline.worker.mark_validating")
@patch("validation_pipeline.worker.fetch_engagement_by_urls")
@patch("validation_pipeline.worker.fetch_corpus_engagement_totals")
@patch("validation_pipeline.worker.fetch_due_predictions")
@patch("validation_pipeline.worker.get_connection")
@patch("validation_pipeline.worker.create_schema")
@patch("validation_pipeline.worker.register_vector")
def test_run_due_validations_failure(
    mock_register,
    mock_create_schema,
    mock_get_connection,
    mock_fetch_due,
    mock_corpus,
    mock_fetch_by_urls,
    mock_mark_validating,
    mock_mark_validated,
    mock_mark_failed,
):
    settings = MagicMock()
    settings.database_url = "postgresql://test"
    settings.validation_rescrape_profile_max_posts = 100
    prediction = _due_prediction()
    mock_get_connection.return_value = MagicMock()
    mock_fetch_due.return_value = [prediction]
    mock_corpus.return_value = [10, 20]
    mock_fetch_by_urls.return_value = {}

    batch = run_due_validations(settings)

    assert batch.processed == 1
    assert batch.validated == 0
    assert batch.failed == 1
    mock_mark_failed.assert_called_once()
    mock_mark_validated.assert_not_called()
