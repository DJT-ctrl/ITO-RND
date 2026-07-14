"""Tests for Phase H routing (centroids) and Phase G hybrid gates."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from feedback.hybrid import (
    HybridGenerationResult,
    generate_hybrid_feedback,
    should_use_llm_for_delta,
)
from feedback.jobs.run_cluster_centroids import mean_vector
from feedback.routing import (
    assign_cluster_id,
    cosine_distance,
    nearest_centroid_cluster_id,
)
from feedback.schemas import DeltaSummary, FeedbackPayload
from validation_pipeline.schemas import PredictionRecord


def test_cosine_and_nearest_centroid_deterministic():
    centroids = [
        ("a", [1.0, 0.0, 0.0]),
        ("b", [0.0, 1.0, 0.0]),
    ]
    assert nearest_centroid_cluster_id([0.9, 0.1, 0.0], centroids) == "a"
    assert nearest_centroid_cluster_id([0.1, 0.9, 0.0], centroids) == "b"
    assert cosine_distance([1.0, 0.0], [1.0, 0.0]) == 0.0


def test_assign_cluster_id_prefers_centroid_when_embedding_present():
    content = "A calm product update with enough words here for prose."
    metadata = assign_cluster_id(content, 2000)
    assert metadata == "short_prose_micro"
    routed = assign_cluster_id(
        content,
        2000,
        embedding=[0.0, 1.0, 0.0],
        centroids=[
            (metadata, [1.0, 0.0, 0.0]),
            ("other_bucket", [0.0, 1.0, 0.0]),
        ],
    )
    assert routed == "other_bucket"
    # Same inputs → same cluster
    assert (
        assign_cluster_id(
            content,
            2000,
            embedding=[0.0, 1.0, 0.0],
            centroids=[
                (metadata, [1.0, 0.0, 0.0]),
                ("other_bucket", [0.0, 1.0, 0.0]),
            ],
        )
        == routed
    )


def test_mean_vector():
    assert mean_vector([[2.0, 4.0], [4.0, 6.0]]) == [3.0, 5.0]


def test_should_use_llm_for_delta():
    assert should_use_llm_for_delta(12.0, 10.0) is True
    assert should_use_llm_for_delta(-12.0, 10.0) is True
    assert should_use_llm_for_delta(3.0, 10.0) is False


def _validated_record(*, delta: float = 12.0) -> PredictionRecord:
    return PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="x",
        linkedin_url="https://linkedin.com/x",
        content="A calm product update with enough words here.",
        posted_at=datetime.now(timezone.utc),
        predicted_engagement_percentile=70.0,
        actual_engagement_percentile=70.0 + delta,
        prediction_delta=delta,
        validation_due_at=datetime.now(timezone.utc),
        status="validated",
        likes_delta=5.0,
    )


def test_hybrid_skips_when_llm_disabled():
    settings = MagicMock()
    settings.validation_feedback_llm_enabled = False
    settings.validation_feedback_llm_delta_min = 10.0
    result = generate_hybrid_feedback(_validated_record(), settings)
    assert isinstance(result, HybridGenerationResult)
    assert result.used_llm is False
    assert result.feedback_version == "v1"
    assert result.skip_reason == "llm_disabled"


def test_hybrid_skips_small_delta_even_when_llm_enabled():
    settings = MagicMock()
    settings.validation_feedback_llm_enabled = True
    settings.validation_feedback_llm_delta_min = 10.0
    result = generate_hybrid_feedback(_validated_record(delta=3.0), settings)
    assert result.used_llm is False
    assert result.skip_reason == "delta_within_accurate_band"


def test_same_embedding_and_centroids_always_same_cluster_id():
    """CI reproducibility: identical embedding + fixed centroids → same cluster."""
    content = "Launch notes with enough words for a short prose micro bucket."
    embedding = [0.2, 0.8, 0.1]
    centroids = [
        ("short_prose_micro", [1.0, 0.0, 0.0]),
        ("medium_list_mid", [0.0, 1.0, 0.0]),
        ("long_question_macro", [0.0, 0.0, 1.0]),
    ]
    first = assign_cluster_id(content, 5000, embedding=embedding, centroids=centroids)
    for _ in range(20):
        assert (
            assign_cluster_id(content, 5000, embedding=embedding, centroids=centroids)
            == first
        )
    assert first == "medium_list_mid"


def test_fallback_chain_centroid_then_metadata_then_calibration_none():
    """Centroid → metadata routing, then calibration none when N < n_min."""
    from feedback.calibration import apply_calibration
    from feedback.schemas import CalibrationStats
    from feedback.store import resolve_calibration_stats

    content = "A calm product update with enough words here for prose."
    # No embedding → metadata bucket
    metadata_id = assign_cluster_id(content, 2000)
    assert metadata_id == "short_prose_micro"
    # Embedding + empty centroids → metadata fallback
    assert (
        assign_cluster_id(content, 2000, embedding=[1.0, 0.0], centroids=[])
        == metadata_id
    )
    # Embedding + centroids → centroid wins
    assert (
        assign_cluster_id(
            content,
            2000,
            embedding=[0.0, 1.0],
            centroids=[(metadata_id, [1.0, 0.0]), ("other", [0.0, 1.0])],
        )
        == "other"
    )

    # Calibration fallback: thin cluster → global; empty global → none applied
    conn = MagicMock()
    with patch("feedback.store.fetch_cluster_stats", return_value=None), patch(
        "feedback.store.fetch_calibration_stats",
        return_value=CalibrationStats(n_validated=5, mean_delta=-8.0, source="global"),
    ):
        stats = resolve_calibration_stats(
            conn, cluster_id="thin_cluster", cluster_n_min=50
        )
    assert stats.source == "global"
    assert stats.n_validated == 5
    calibrated = apply_calibration(70.0, stats.mean_delta, stats.n_validated, n_min=30)
    assert calibrated.applied is False
    assert calibrated.skip_reason == "below_n_min"
    assert calibrated.calibrated_percentile == 70.0
