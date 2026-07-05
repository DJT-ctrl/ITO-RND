"""Unit tests for Phase B pattern/correlation analysis (processors/pattern_analysis.py).

Uses small synthetic datasets with an obvious, known pattern baked in so
the expected result of each analysis is unambiguous — these tests are
checking the statistics are computed correctly, not discovering anything.
"""

import pytest

from processors.pattern_analysis import (
    correlate_numeric_features,
    feature_importance,
    group_engagement_by_tag,
)


def _record(**overrides) -> dict:
    base = {
        "hook_type": "other",
        "tone": "professional",
        "day_of_week": "Monday",
        "topic": "career",
        "word_count": 50,
        "char_count": 300,
        "hashtag_count": 2,
        "emoji_count": 0,
        "hour_of_day": 10,
        "has_media": False,
        "is_job_post": False,
        "has_explicit_cta": False,
        "engagement_zscore": 0.0,
    }
    base.update(overrides)
    return base


# ── group_engagement_by_tag ────────────────────────────────────────────────────

def test_group_by_tag_ranks_higher_engagement_tag_first():
    records = [
        _record(hook_type="question", engagement_zscore=2.0),
        _record(hook_type="question", engagement_zscore=1.8),
        _record(hook_type="announcement", engagement_zscore=-0.5),
        _record(hook_type="announcement", engagement_zscore=-0.3),
    ]
    results = group_engagement_by_tag(records)
    assert "hook_type" in results
    ranked = results["hook_type"]
    assert ranked.index[0] == "question"
    assert ranked.loc["question", "mean"] > ranked.loc["announcement", "mean"]


def test_group_by_tag_skips_tags_missing_from_every_record():
    records = [_record(hook_type=None), _record(hook_type=None)]
    for r in records:
        del r["hook_type"]
    results = group_engagement_by_tag(records)
    assert "hook_type" not in results


def test_group_by_tag_raises_on_empty_input():
    with pytest.raises(ValueError):
        group_engagement_by_tag([])


# ── correlate_numeric_features ─────────────────────────────────────────────────

def test_correlate_numeric_features_finds_strong_positive_correlation():
    # word_count and engagement_zscore rise together in lockstep.
    records = [_record(word_count=wc, engagement_zscore=wc / 10) for wc in range(10, 100, 10)]
    correlations = correlate_numeric_features(records)
    assert correlations["word_count"] > 0.95


def test_correlate_numeric_features_finds_strong_negative_correlation():
    records = [_record(hashtag_count=hc, engagement_zscore=-hc) for hc in range(1, 10)]
    correlations = correlate_numeric_features(records)
    assert correlations["hashtag_count"] < -0.95


# ── feature_importance ─────────────────────────────────────────────────────────

def test_feature_importance_raises_below_min_rows():
    records = [_record() for _ in range(5)]
    with pytest.raises(ValueError):
        feature_importance(records, min_rows=50)


def test_feature_importance_returns_series_when_enough_rows():
    records = [
        _record(word_count=wc, engagement_zscore=wc / 10) for wc in range(10, 610, 10)
    ]  # 60 rows, comfortably above the default min_rows
    importances = feature_importance(records, min_rows=50)
    assert "word_count" in importances.index
    # word_count fully determines the target here, so it should dominate.
    assert importances["word_count"] == importances.max()
