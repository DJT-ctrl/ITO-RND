"""Tests for deterministic cluster routing (Phase C)."""

from feedback.routing import (
    assign_cluster_id,
    content_length_bucket,
    follower_bucket,
    format_bucket,
)
from feedback.schemas import CalibrationStats, ClusterStats
from feedback.store import resolve_calibration_stats
from unittest.mock import MagicMock, patch


def test_length_buckets():
    assert content_length_bucket("word " * 10) == "short"
    assert content_length_bucket("word " * 80) == "medium"
    assert content_length_bucket("word " * 200) == "long"


def test_format_list_and_question():
    list_post = "\n".join(f"- item {i} about marketing" for i in range(5))
    assert format_bucket(list_post) == "list"
    assert format_bucket("What is the best AI tool for SEO?") == "question"
    assert format_bucket("A calm update on our product roadmap.") == "prose"


def test_follower_buckets():
    assert follower_bucket(None) == "unknown"
    assert follower_bucket(500) == "nano"
    assert follower_bucket(5_000) == "micro"
    assert follower_bucket(50_000) == "mid"
    assert follower_bucket(500_000) == "macro"


def test_assign_cluster_id_deterministic():
    content = "What should founders ship first?\n" + ("more words " * 20)
    a = assign_cluster_id(content, 5_000)
    b = assign_cluster_id(content, 5_000)
    assert a == b
    assert a == "short_question_micro"


def test_generate_assigns_cluster_id():
    from datetime import datetime, timezone
    from uuid import uuid4

    from feedback.generate import generate_template_feedback_from_scores
    from validation_pipeline.schemas import PredictionRecord, ValidationScores

    now = datetime.now(timezone.utc)
    prediction = PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="p1",
        linkedin_url="https://linkedin.com/posts/p1",
        content="A calm update on our product roadmap with enough words " * 3,
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
    payload = generate_template_feedback_from_scores(
        prediction, scores, follower_count=2_000
    )
    assert payload.cluster_id == "short_prose_micro"


@patch("feedback.store.fetch_cluster_stats")
@patch("feedback.store.fetch_calibration_stats")
def test_resolve_calibration_prefers_cluster(mock_global, mock_cluster):
    mock_cluster.return_value = ClusterStats(
        cluster_id="short_prose_micro",
        sample_count=60,
        mean_delta=-8.0,
    )
    conn = MagicMock()
    stats = resolve_calibration_stats(
        conn, cluster_id="short_prose_micro", cluster_n_min=50
    )
    assert stats.source == "cluster"
    assert stats.mean_delta == -8.0
    mock_global.assert_not_called()


@patch("feedback.store.fetch_cluster_stats")
@patch("feedback.store.fetch_calibration_stats")
def test_resolve_calibration_falls_back_to_global(mock_global, mock_cluster):
    mock_cluster.return_value = ClusterStats(
        cluster_id="short_prose_micro",
        sample_count=10,
        mean_delta=-8.0,
    )
    mock_global.return_value = CalibrationStats(
        n_validated=40, mean_delta=-3.0, source="global"
    )
    conn = MagicMock()
    stats = resolve_calibration_stats(
        conn, cluster_id="short_prose_micro", cluster_n_min=50
    )
    assert stats.source == "global"
    assert stats.mean_delta == -3.0
    assert stats.cluster_id == "short_prose_micro"
