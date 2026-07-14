"""Tests for persisted prediction learning telemetry."""

from validation_pipeline.prediction_telemetry import (
    build_prediction_telemetry,
    estimate_tokens,
)


def test_build_prediction_telemetry_captures_learning_decisions():
    context = "grounded lesson text"
    telemetry = build_prediction_telemetry(
        {
            "percentile": 58.0,
            "raw_percentile": 72.0,
            "calibrated_percentile": 58.0,
            "calibration_applied": True,
            "mean_delta": -14.0,
            "n_validated": 60,
            "calibration_source": "cluster",
            "cluster_id": "short_prose_micro",
        },
        calibration_enabled=True,
        feedback_injection_enabled=True,
        feedback_context=context,
        feedback_count=3,
        cluster_id="short_prose_micro",
    )

    assert telemetry.raw_percentile == 72.0
    assert telemetry.calibrated_percentile == 58.0
    assert telemetry.calibration_applied is True
    assert telemetry.feedback_injected is True
    assert telemetry.feedback_count == 3
    assert telemetry.feedback_chars == len(context)
    assert telemetry.feedback_token_estimate == estimate_tokens(context)


def test_build_prediction_telemetry_records_disabled_paths():
    telemetry = build_prediction_telemetry(
        {"percentile": 62.5},
        calibration_enabled=False,
        feedback_injection_enabled=False,
        feedback_context=None,
        feedback_count=0,
        cluster_id=None,
    )

    assert telemetry.raw_percentile == 62.5
    assert telemetry.calibrated_percentile == 62.5
    assert telemetry.calibration_source == "none"
    assert telemetry.feedback_version is None
    assert telemetry.shadow_percentile is None
    assert telemetry.llm_percentile is None


def test_build_prediction_telemetry_includes_injectability_fields():
    telemetry = build_prediction_telemetry(
        {"percentile": 70.0, "calibration_applied": True, "feedback_count": 2},
        calibration_enabled=False,
        feedback_injection_enabled=False,
        feedback_context=None,
        feedback_count=2,
        cluster_id="short_prose_micro",
        injectability={
            "llm_percentile": 90.0,
            "shadow_percentile": 73.0,
            "shadow_calibration_applied": True,
            "shadow_feedback_count": 2,
            "injectability_mode": "shadow_only",
            "soft_blend_weight": 0.15,
        },
    )
    assert telemetry.llm_percentile == 90.0
    assert telemetry.shadow_percentile == 73.0
    assert telemetry.shadow_calibration_applied is True
    assert telemetry.shadow_feedback_count == 2
    assert telemetry.injectability_mode == "shadow_only"
    assert telemetry.soft_blend_weight == 0.15
