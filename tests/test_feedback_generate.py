"""Tests for Phase B template feedback generation and store helpers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from feedback.batch import try_store_feedback_after_validation
from feedback.generate import (
    direction_from_delta,
    generate_template_feedback,
    generate_template_feedback_from_scores,
)
from feedback.store import upsert_prediction_feedback
from validation_pipeline.schemas import PredictionRecord, ValidationScores


def test_direction_accurate_small_delta():
    assert direction_from_delta(0.0) == "accurate"
    assert direction_from_delta(4.9) == "accurate"
    assert direction_from_delta(-4.9) == "accurate"


def test_direction_over_and_under():
    assert direction_from_delta(-14.0) == "overestimated"
    assert direction_from_delta(12.0) == "underestimated"


def test_generate_template_feedback_overestimate_grounded():
    prediction_id = uuid4()
    payload = generate_template_feedback(
        prediction_id,
        predicted_percentile=72.0,
        actual_percentile=58.0,
        prediction_delta=-14.0,
        accuracy_score=86.0,
        prediction_method="audience_adjusted",
        likes_delta=-20.0,
    )
    assert payload.delta_summary.direction == "overestimated"
    assert payload.delta_summary.prediction_delta == -14.0
    assert any("Overestimated" in s for s in payload.what_missed)
    assert any("72.0" in s or "72" in s for s in payload.what_missed)
    assert any("lower percentiles" in s for s in payload.lessons_for_similar_posts)
    assert any("likes" in s.lower() for s in payload.what_missed)


def test_generate_template_feedback_accurate():
    payload = generate_template_feedback(
        uuid4(),
        predicted_percentile=50.0,
        actual_percentile=52.0,
        prediction_delta=2.0,
    )
    assert payload.delta_summary.direction == "accurate"
    assert payload.what_worked
    assert any("within ±5" in s for s in payload.what_worked)


def test_generate_from_scores():
    now = datetime.now(timezone.utc)
    prediction = PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        content="hello",
        posted_at=now,
        predicted_engagement_percentile=60.0,
        prediction_method="raw_fallback",
        validation_due_at=now,
    )
    scores = ValidationScores(
        actual_engagement_percentile=70.0,
        prediction_delta=10.0,
        accuracy_score=90.0,
        corpus_sample_size=100,
        likes_delta=5.0,
        comments_delta=1.0,
        shares_delta=0.0,
        total_engagement_delta=6.0,
    )
    payload = generate_template_feedback_from_scores(prediction, scores)
    assert payload.delta_summary.direction == "underestimated"
    assert payload.prediction_id == prediction.prediction_id


def test_upsert_prediction_feedback_sql():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    feedback_id = uuid4()
    prediction_id = uuid4()
    generated_at = datetime.now(timezone.utc)
    payload = generate_template_feedback(
        prediction_id,
        predicted_percentile=40.0,
        actual_percentile=55.0,
        prediction_delta=15.0,
    )
    cursor.fetchone.return_value = (
        feedback_id,
        prediction_id,
        None,
        payload.model_dump(mode="json"),
        "v1",
        generated_at,
        "template",
    )

    record = upsert_prediction_feedback(conn, payload)
    assert record.feedback_id == feedback_id
    assert record.feedback_json.delta_summary.prediction_delta == 15.0
    conn.commit.assert_called_once()
    sql = cursor.execute.call_args[0][0]
    assert "ON CONFLICT (prediction_id, feedback_version)" in sql


@patch("feedback.batch.upsert_prediction_feedback")
@patch("feedback.batch.create_schema")
@patch("feedback.batch.get_connection")
def test_try_store_feedback_after_validation_success(
    mock_get_connection,
    mock_create_schema,
    mock_upsert,
):
    settings = MagicMock()
    settings.validation_feedback_enabled = True
    mock_get_connection.return_value = MagicMock()
    now = datetime.now(timezone.utc)
    prediction = PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        content="hello",
        posted_at=now,
        predicted_engagement_percentile=60.0,
        validation_due_at=now,
    )
    scores = ValidationScores(
        actual_engagement_percentile=55.0,
        prediction_delta=-5.0,
        accuracy_score=95.0,
        corpus_sample_size=3,
        likes_delta=0.0,
        comments_delta=0.0,
        shares_delta=0.0,
        total_engagement_delta=0.0,
    )
    mock_upsert.return_value = MagicMock()

    result = try_store_feedback_after_validation(prediction, scores, settings)
    assert result is not None
    mock_upsert.assert_called_once()


def test_try_store_feedback_disabled():
    settings = MagicMock()
    settings.validation_feedback_enabled = False
    now = datetime.now(timezone.utc)
    prediction = PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        content="hello",
        posted_at=now,
        predicted_engagement_percentile=60.0,
        validation_due_at=now,
    )
    scores = ValidationScores(
        actual_engagement_percentile=55.0,
        prediction_delta=-5.0,
        accuracy_score=95.0,
        corpus_sample_size=3,
        likes_delta=0.0,
        comments_delta=0.0,
        shares_delta=0.0,
        total_engagement_delta=0.0,
    )
    assert try_store_feedback_after_validation(prediction, scores, settings) is None
