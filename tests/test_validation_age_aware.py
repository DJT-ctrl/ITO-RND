"""Tests for validation age-aware classification and learning filters."""

from datetime import datetime, timedelta, timezone

from validation_pipeline.age_aware import (
    age_aware_learning_sql,
    classify_validation_mode,
    is_learning_eligible,
)


def test_classify_live_48h_in_window():
    posted = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    validated = posted + timedelta(hours=48)
    age, mode = classify_validation_mode(
        posted_at=posted,
        validated_at=validated,
        horizon_hours=48,
        is_backtest=False,
        tolerance_hours=6,
    )
    assert mode == "live_48h"
    assert age == 48.0


def test_classify_forced_early_young_live():
    posted = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    validated = posted + timedelta(hours=5)
    age, mode = classify_validation_mode(
        posted_at=posted,
        validated_at=validated,
        horizon_hours=48,
        is_backtest=False,
        tolerance_hours=6,
    )
    assert mode == "forced_early"
    assert age == 5.0


def test_classify_live_out_of_window_old():
    posted = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    validated = posted + timedelta(hours=120)
    age, mode = classify_validation_mode(
        posted_at=posted,
        validated_at=validated,
        horizon_hours=48,
        is_backtest=False,
        tolerance_hours=6,
    )
    assert mode == "live_out_of_window"
    assert age == 120.0


def test_classify_backtest_mature():
    posted = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    validated = posted + timedelta(hours=96)
    age, mode = classify_validation_mode(
        posted_at=posted,
        validated_at=validated,
        horizon_hours=48,
        is_backtest=True,
        mature_min_hours=72,
    )
    assert mode == "backtest_mature"
    assert age == 96.0


def test_classify_backtest_too_young_is_forced_early():
    posted = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    validated = posted + timedelta(hours=50)
    _, mode = classify_validation_mode(
        posted_at=posted,
        validated_at=validated,
        horizon_hours=48,
        is_backtest=True,
        mature_min_hours=72,
    )
    assert mode == "forced_early"


def test_learning_eligible_when_flag_off():
    assert is_learning_eligible("forced_early", age_aware_enabled=False) is True


def test_learning_eligible_excludes_forced_early_when_on():
    assert is_learning_eligible("forced_early", age_aware_enabled=True) is False
    assert is_learning_eligible("live_48h", age_aware_enabled=True) is True
    assert is_learning_eligible("backtest_mature", age_aware_enabled=True) is True
    assert is_learning_eligible(None, age_aware_enabled=True) is True


def test_age_aware_sql_disabled():
    clause, params = age_aware_learning_sql(enabled=False)
    assert clause == ""
    assert params == []


def test_age_aware_sql_enabled():
    clause, params = age_aware_learning_sql(enabled=True, alias="p")
    assert "validation_mode" in clause
    assert params == ["forced_early"]
