"""Tests for validation_pipeline.scoring."""

from datetime import datetime, timezone
from uuid import uuid4

from validation_pipeline.schemas import EngagementActuals, PredictionRecord
from validation_pipeline.scoring import (
    compute_corpus_percentile,
    compute_validation_scores,
    corpus_size_warning,
)


def _prediction(percentile: float, **kwargs) -> PredictionRecord:
    now = datetime.now(timezone.utc)
    defaults = dict(
        prediction_id=uuid4(),
        linkedin_post_id="post-1",
        linkedin_url="https://linkedin.com/posts/1",
        content="hello",
        posted_at=now,
        predicted_engagement_percentile=percentile,
        predicted_total_engagement=40,
        predicted_likes=30,
        predicted_comments=8,
        predicted_shares=2,
        validation_due_at=now,
    )
    defaults.update(kwargs)
    return PredictionRecord(**defaults)


def test_compute_corpus_percentile_empty_corpus():
    assert compute_corpus_percentile(100, []) == 50.0


def test_compute_corpus_percentile_highest_in_corpus():
    corpus = [10, 20, 30, 40, 50]
    assert compute_corpus_percentile(100, corpus) == 100.0
    assert compute_corpus_percentile(50, corpus) >= 90.0


def test_compute_corpus_percentile_uses_log1p_ranking():
    corpus = [0, 1, 10, 100, 1000]
    low = compute_corpus_percentile(1, corpus)
    high = compute_corpus_percentile(1000, corpus)
    assert high > low


def test_compute_validation_scores_delta_and_accuracy():
    prediction = _prediction(70.0)
    actuals = EngagementActuals(likes=10, comments=2, shares=1, total_engagement=13)
    corpus = [5, 10, 13, 20, 50]
    scores = compute_validation_scores(actuals, prediction, corpus)
    assert scores.prediction_delta == round(scores.actual_engagement_percentile - 70.0, 2)
    assert scores.accuracy_score == round(max(0.0, 100.0 - abs(scores.prediction_delta)), 2)
    assert scores.likes_delta == -20.0
    assert scores.comments_delta == -6.0
    assert scores.shares_delta == -1.0
    assert scores.total_engagement_delta == -27.0


def test_corpus_size_warning():
    assert corpus_size_warning([1] * 10) is not None
    assert corpus_size_warning([1] * 40) is None
