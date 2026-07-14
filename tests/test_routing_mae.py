"""Tests for offline metadata vs centroid routing MAE comparison."""

from uuid import UUID

import pytest

from feedback.routing_mae import RoutingReplayRow, run_routing_mae_replay


def _rows(count: int = 40) -> list[RoutingReplayRow]:
    rows: list[RoutingReplayRow] = []
    for index in range(count):
        # Alternate embeddings so centroid routing can diverge from metadata.
        embedding = [1.0, 0.0] if index % 2 == 0 else [0.0, 1.0]
        rows.append(
            RoutingReplayRow(
                prediction_id=UUID(int=index + 1),
                actual_percentile=60.0,
                raw_percentile=50.0,
                content="A calm product update with enough words here for prose.",
                follower_count=2000,
                embedding=embedding,
            )
        )
    return rows


def test_routing_mae_builds_both_modes():
    centroids = [
        ("short_prose_micro", [1.0, 0.0]),
        ("other_bucket", [0.0, 1.0]),
    ]
    report = run_routing_mae_replay(
        _rows(),
        centroids,
        holdout_size=10,
        n_min=5,
    )
    assert report.holdout_rows == 10
    assert report.training_rows == 30
    assert report.centroid_count == 2
    assert [mode.mode for mode in report.modes] == ["metadata", "centroid"]
    assert report.modes[0].sample_count == 10
    assert report.modes[1].sample_count == 10
    assert report.modes[1].rows_with_embedding == 10


def test_routing_mae_requires_training_beyond_holdout():
    with pytest.raises(ValueError, match="Need more than 10"):
        run_routing_mae_replay(_rows(10), [], holdout_size=10)
