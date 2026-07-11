"""Tests for validation_pipeline.store (mocked psycopg)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from validation_pipeline.schemas import NewPrediction
from validation_pipeline.store import insert_prediction, prediction_exists


def test_prediction_exists_true():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (1,)
    assert prediction_exists(conn, "post-123") is True


def test_prediction_exists_false():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = None
    assert prediction_exists(conn, "post-123") is False


def test_insert_prediction_returns_record():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    prediction_id = uuid4()
    created_at = datetime.now(timezone.utc)
    cursor.fetchone.return_value = (prediction_id, created_at)

    new = NewPrediction(
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        author_public_id="author",
        content="hello world",
        posted_at=created_at,
        predicted_engagement_percentile=72.5,
        predicted_total_engagement=40,
        predicted_likes=30,
        predicted_comments=8,
        predicted_shares=2,
        prediction_method="raw_fallback",
        neighbor_count=10,
        validation_due_at=created_at,
    )

    record = insert_prediction(conn, new)
    assert record.prediction_id == prediction_id
    assert record.predicted_engagement_percentile == 72.5
    assert record.predicted_likes == 30
    assert record.status == "scheduled"
    conn.commit.assert_called_once()
