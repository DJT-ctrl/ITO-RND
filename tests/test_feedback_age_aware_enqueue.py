"""Tests for age-aware feedback enqueue gating."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch
from uuid import uuid4

from feedback.batch import try_enqueue_feedback_after_validation
from validation_pipeline.schemas import PredictionRecord


def _prediction(*, mode: Optional[str]) -> PredictionRecord:
    now = datetime.now(timezone.utc)
    return PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        content="hello",
        posted_at=now,
        predicted_engagement_percentile=50.0,
        validation_due_at=now,
        validation_mode=mode,  # type: ignore[arg-type]
    )


def test_enqueue_skips_forced_early_when_age_aware_on():
    settings = MagicMock()
    settings.validation_feedback_enabled = True
    settings.validation_age_aware_enabled = True

    with patch("feedback.batch.enqueue_feedback_job") as enqueue:
        ok = try_enqueue_feedback_after_validation(
            _prediction(mode="forced_early"), settings
        )
    assert ok is False
    enqueue.assert_not_called()


def test_enqueue_allows_live_48h_when_age_aware_on():
    settings = MagicMock()
    settings.validation_feedback_enabled = True
    settings.validation_age_aware_enabled = True
    settings.database_url = "postgresql://test"

    with patch("feedback.batch.get_connection") as get_conn, patch(
        "feedback.batch.create_schema"
    ), patch("feedback.batch.enqueue_feedback_job") as enqueue:
        get_conn.return_value = MagicMock()
        ok = try_enqueue_feedback_after_validation(
            _prediction(mode="live_48h"), settings
        )
    assert ok is True
    enqueue.assert_called_once()


def test_enqueue_allows_forced_early_when_age_aware_off():
    settings = MagicMock()
    settings.validation_feedback_enabled = True
    settings.validation_age_aware_enabled = False
    settings.database_url = "postgresql://test"

    with patch("feedback.batch.get_connection") as get_conn, patch(
        "feedback.batch.create_schema"
    ), patch("feedback.batch.enqueue_feedback_job") as enqueue:
        get_conn.return_value = MagicMock()
        ok = try_enqueue_feedback_after_validation(
            _prediction(mode="forced_early"), settings
        )
    assert ok is True
    enqueue.assert_called_once()
