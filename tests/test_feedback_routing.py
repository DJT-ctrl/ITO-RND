"""Tests for deterministic cluster routing (Phase C + T10.7)."""

from feedback.routing import (
    assign_cluster_id,
    cluster_fallback_ids,
    cluster_label,
    content_length_bucket,
    follower_bucket,
    format_bucket,
    metadata_cluster_id,
    shape_cluster_id_from,
    topic_from_cluster_id,
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


def test_assign_cluster_id_with_niche_prefix():
    content = "What should founders ship first?\n" + ("more words " * 20)
    assert assign_cluster_id(content, 5_000, niche="fintech") == (
        "fintech_short_question_micro"
    )
    assert assign_cluster_id(content, 5_000, niche=None) == "short_question_micro"
    assert assign_cluster_id(content, 5_000, niche="") == "short_question_micro"
    assert assign_cluster_id(content, 5_000, niche="not_a_real_niche") == (
        "short_question_micro"
    )


def test_underscored_niche_parsers():
    cid = "saas_b2b_medium_list_micro"
    assert shape_cluster_id_from(cid) == "medium_list_micro"
    assert topic_from_cluster_id(cid) == "saas_b2b"
    assert cluster_fallback_ids(cid) == [cid, "medium_list_micro"]

    ai = "ai_tech_short_prose_nano"
    assert shape_cluster_id_from(ai) == "short_prose_nano"
    assert topic_from_cluster_id(ai) == "ai_tech"

    legacy = "short_prose_micro"
    assert shape_cluster_id_from(legacy) == legacy
    assert topic_from_cluster_id(legacy) is None
    assert cluster_fallback_ids(legacy) == [legacy]


def test_cluster_label_topic_and_shape():
    assert "fintech" in cluster_label("fintech_short_prose_micro")
    assert "short" in cluster_label("fintech_short_prose_micro")
    assert cluster_label("short_prose_micro") == (
        "short prose posts (micro followers)"
    )
    assert "saas_b2b" in cluster_label("saas_b2b_medium_list_mid")


def test_metadata_cluster_id_niche_kwarg():
    content = "A calm update on our product roadmap."
    assert metadata_cluster_id(content, 2000) == "short_prose_micro"
    assert metadata_cluster_id(content, 2000, niche="career") == (
        "career_short_prose_micro"
    )


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
    with_niche = generate_template_feedback_from_scores(
        prediction, scores, follower_count=2_000, niche="fintech"
    )
    assert with_niche.cluster_id == "fintech_short_prose_micro"


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


@patch("feedback.store.fetch_calibration_stats")
@patch("feedback.store.fetch_cluster_stats")
def test_resolve_calibration_topic_falls_back_to_shape(mock_cluster, mock_global):
    def _stats(conn, cluster_id):
        if cluster_id == "fintech_short_prose_micro":
            return ClusterStats(
                cluster_id=cluster_id,
                sample_count=5,
                mean_delta=-1.0,
            )
        if cluster_id == "short_prose_micro":
            return ClusterStats(
                cluster_id=cluster_id,
                sample_count=60,
                mean_delta=-9.0,
            )
        return None

    mock_cluster.side_effect = _stats
    conn = MagicMock()
    stats = resolve_calibration_stats(
        conn,
        cluster_id="fintech_short_prose_micro",
        cluster_n_min=50,
    )
    assert stats.source == "cluster"
    assert stats.cluster_id == "short_prose_micro"
    assert stats.mean_delta == -9.0
    mock_global.assert_not_called()
