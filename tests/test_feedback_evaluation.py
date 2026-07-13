"""Tests for leakage-safe feedback-loop offline replay."""

from uuid import UUID

import pytest

from feedback.evaluation import ReplayRow, run_offline_replay


def _rows(count: int = 40) -> list[ReplayRow]:
    return [
        ReplayRow(
            prediction_id=UUID(int=index + 1),
            actual_percentile=60.0,
            raw_percentile=50.0,
            cluster_id="short_prose_micro",
        )
        for index in range(count)
    ]


def test_replay_builds_four_arms_without_holdout_leakage():
    report = run_offline_replay(
        _rows(),
        holdout_size=10,
        global_n_min=20,
        cluster_n_min=100,
    )

    assert report.training_rows == 30
    assert report.holdout_rows == 10
    assert report.global_mean_delta == 10.0
    assert [arm.arm for arm in report.arms] == [
        "raw_no_feedback",
        "raw_with_feedback",
        "calibrated_no_feedback",
        "calibrated_with_feedback",
    ]
    assert report.arms[0].mae == 10.0
    assert report.arms[2].mae == 0.0


def test_injection_arms_report_identical_numeric_scores():
    report = run_offline_replay(
        _rows(),
        holdout_size=10,
        global_n_min=20,
        cluster_n_min=100,
    )

    assert report.arms[0].mae == report.arms[1].mae
    assert report.arms[2].mae == report.arms[3].mae
    assert any("deterministic" in note for note in report.notes)


def test_replay_requires_training_rows_beyond_holdout():
    with pytest.raises(ValueError, match="Need more than 30"):
        run_offline_replay(_rows(30), holdout_size=30)
