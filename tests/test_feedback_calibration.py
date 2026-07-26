"""Tests for feedback.calibration and related store/predict helpers."""

from unittest.mock import MagicMock, patch

from feedback.calibration import apply_calibration, compute_mean_delta
from feedback.schemas import CalibrationStats
from feedback.store import fetch_calibration_stats
from validation_pipeline.predict import _apply_calibration_to_neighbor_prediction


def test_compute_mean_delta_empty():
    assert compute_mean_delta([]) == 0.0


def test_compute_mean_delta_average():
    # Overestimates: actual − predicted → negative deltas
    assert compute_mean_delta([-14.0, -10.0, -6.0]) == -10.0


def test_apply_calibration_below_n_min_unchanged():
    result = apply_calibration(70.0, -10.0, n=5, n_min=30)
    assert result.applied is False
    assert result.calibrated_percentile == 70.0
    assert result.raw_percentile == 70.0
    assert result.skip_reason == "below_n_min"


def test_apply_calibration_sign_convention_overestimate():
    # Predicted 72, actual 58 → delta −14; adding mean_delta pulls next raw down
    result = apply_calibration(72.0, -14.0, n=30, n_min=30)
    assert result.applied is True
    assert result.calibrated_percentile == 58.0
    assert result.skip_reason is None


def test_apply_calibration_at_n_min_applies():
    result = apply_calibration(70.0, -10.0, n=30, n_min=30)
    assert result.applied is True
    assert result.calibrated_percentile == 60.0


def test_apply_calibration_clamps_low():
    result = apply_calibration(5.0, -10.0, n=50, n_min=30)
    assert result.calibrated_percentile == 0.0


def test_apply_calibration_clamps_high():
    result = apply_calibration(95.0, 10.0, n=50, n_min=30)
    assert result.calibrated_percentile == 100.0


def test_fetch_calibration_stats_empty():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (0, None)

    stats = fetch_calibration_stats(conn)
    assert stats == CalibrationStats(n_validated=0, mean_delta=0.0, source="none")


def test_fetch_calibration_stats_with_bias():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (42, -8.25)

    stats = fetch_calibration_stats(conn)
    assert stats.n_validated == 42
    assert stats.mean_delta == -8.25
    assert stats.source == "global"


def test_fetch_calibration_stats_age_aware_filters_forced_early():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = (10, -2.0)

    stats = fetch_calibration_stats(conn, age_aware_enabled=True)
    assert stats.n_validated == 10
    sql = cursor.execute.call_args[0][0]
    assert "validation_mode" in sql
    assert cursor.execute.call_args[0][1] == ("forced_early",)


def _neighbor() -> dict:
    return {
        "percentile": 72.0,
        "total_engagement_estimate": 100,
        "predicted_likes": 80,
        "predicted_comments": 15,
        "predicted_shares": 5,
        "method": "audience_adjusted",
        "neighbor_count": 10,
    }


def test_apply_calibration_helper_disabled_passthrough():
    settings = MagicMock()
    settings.validation_calibration_enabled = False
    neighbor = _neighbor()
    out = _apply_calibration_to_neighbor_prediction(neighbor, settings)
    assert out is neighbor
    assert out["percentile"] == 72.0


@patch("validation_pipeline.predict.get_connection")
@patch("validation_pipeline.predict.create_schema")
@patch("validation_pipeline.predict.resolve_calibration_stats")
def test_apply_calibration_helper_below_n_min(
    mock_stats,
    _mock_schema,
    mock_conn,
):
    settings = MagicMock()
    settings.validation_calibration_enabled = True
    settings.validation_calibration_n_min = 30
    settings.validation_cluster_n_min = 50
    mock_conn.return_value = MagicMock()
    mock_stats.return_value = CalibrationStats(
        n_validated=5, mean_delta=-14.0, source="global"
    )

    out = _apply_calibration_to_neighbor_prediction(
        _neighbor(), settings, content="hello world"
    )
    assert out["percentile"] == 72.0
    assert out["calibration_applied"] is False
    assert out["calibration_skip_reason"] == "below_n_min"
    assert out["raw_percentile"] == 72.0
    assert out["method"] == "audience_adjusted"
    assert out["cluster_id"]


@patch("validation_pipeline.predict.get_connection")
@patch("validation_pipeline.predict.create_schema")
@patch("validation_pipeline.predict.resolve_calibration_stats")
def test_apply_calibration_helper_applies_and_tags_method(
    mock_stats,
    _mock_schema,
    mock_conn,
):
    settings = MagicMock()
    settings.validation_calibration_enabled = True
    settings.validation_calibration_n_min = 30
    settings.validation_cluster_n_min = 50
    mock_conn.return_value = MagicMock()
    mock_stats.return_value = CalibrationStats(
        n_validated=40, mean_delta=-14.0, source="global"
    )

    out = _apply_calibration_to_neighbor_prediction(
        _neighbor(), settings, content="hello world"
    )
    assert out["percentile"] == 58.0
    assert out["calibrated_percentile"] == 58.0
    assert out["calibration_applied"] is True
    assert out["method"] == "audience_adjusted+calibrated"
    assert out["calibration_source"] == "global"
    mock_conn.return_value.close.assert_called_once()


@patch("validation_pipeline.predict.get_connection")
@patch("validation_pipeline.predict.create_schema")
@patch("validation_pipeline.predict.resolve_calibration_stats")
def test_apply_calibration_helper_cluster_tags_method(
    mock_stats,
    _mock_schema,
    mock_conn,
):
    settings = MagicMock()
    settings.validation_calibration_enabled = True
    settings.validation_calibration_n_min = 30
    settings.validation_cluster_n_min = 50
    mock_conn.return_value = MagicMock()
    mock_stats.return_value = CalibrationStats(
        n_validated=60,
        mean_delta=-14.0,
        cluster_id="short_prose_micro",
        source="cluster",
    )

    out = _apply_calibration_to_neighbor_prediction(
        _neighbor(), settings, content="hello world", follower_count=2000
    )
    assert out["percentile"] == 58.0
    assert out["method"] == "audience_adjusted+cluster+calibrated"
    assert out["calibration_source"] == "cluster"
