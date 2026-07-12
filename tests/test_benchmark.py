"""Unit tests for the batch engagement benchmark (processors/benchmark.py)."""

from types import SimpleNamespace

from processors.benchmark import (
    add_audience_adjusted_benchmark,
    add_engagement_benchmark,
    compute_neighbor_engagement_breakdown,
    compute_neighbor_prediction,
    flag_engagement_anomalies,
)


def _record(total_engagement: int) -> dict:
    return {"post_id": str(total_engagement), "total_engagement": total_engagement}


def test_empty_input_returns_empty_list():
    assert add_engagement_benchmark([]) == []


def test_does_not_mutate_input_records():
    records = [_record(10), _record(50)]
    original_copy = [dict(r) for r in records]
    add_engagement_benchmark(records)
    assert records == original_copy


def test_higher_engagement_gets_higher_percentile_and_zscore():
    records = [_record(5), _record(50), _record(500)]
    enriched = add_engagement_benchmark(records)

    percentiles = [r["engagement_percentile"] for r in enriched]
    zscores = [r["engagement_zscore"] for r in enriched]

    # Ordering must be preserved and monotonically increasing with engagement.
    assert percentiles == sorted(percentiles)
    assert zscores == sorted(zscores)
    assert percentiles[0] < percentiles[-1]
    assert zscores[0] < zscores[-1]


def test_percentiles_are_bounded_between_0_and_100():
    records = [_record(0), _record(10), _record(1000)]
    enriched = add_engagement_benchmark(records)
    for record in enriched:
        assert 0 <= record["engagement_percentile"] <= 100


def test_identical_engagement_gets_identical_scores_and_middle_percentile():
    records = [_record(20), _record(20), _record(20)]
    enriched = add_engagement_benchmark(records)
    percentiles = {r["engagement_percentile"] for r in enriched}
    zscores = {r["engagement_zscore"] for r in enriched}
    # All-tied batch: everyone ranks at the midpoint (50th percentile) and z-score 0.
    assert percentiles == {50.0}
    assert zscores == {0.0}


def test_original_fields_are_preserved():
    records = [_record(10)]
    enriched = add_engagement_benchmark(records)
    assert enriched[0]["post_id"] == "10"
    assert enriched[0]["total_engagement"] == 10


# ── add_audience_adjusted_benchmark ─────────────────────────────────────────

def _follower_record(post_id: str, total_engagement: int, follower_count) -> dict:
    return {"post_id": post_id, "total_engagement": total_engagement, "follower_count": follower_count}


def test_audience_adjusted_empty_input_returns_empty_list():
    assert add_audience_adjusted_benchmark([]) == []


def test_audience_adjusted_does_not_mutate_input():
    records = [_follower_record("1", 100, 1000)]
    original_copy = [dict(r) for r in records]
    add_audience_adjusted_benchmark(records)
    assert records == original_copy


def test_audience_adjusted_none_when_no_follower_count_present():
    """A batch that never went through --with-profile-enrichment (no
    follower_count key at all) must get None for every row \u2014 the
    optional path is a pure no-op when unused."""
    records = [_record(10), _record(50)]
    enriched = add_audience_adjusted_benchmark(records)
    for r in enriched:
        assert r["audience_adjusted_percentile"] is None
        assert r["audience_adjusted_zscore"] is None


def test_audience_adjusted_ranks_smaller_audience_higher_for_same_engagement():
    # Same total_engagement, but "small" has a much smaller following —
    # audience-adjusted ranking must favor it over "big".
    records = [
        _follower_record("small", 100, 500),
        _follower_record("big", 100, 500_000),
    ]
    enriched = add_audience_adjusted_benchmark(records)
    by_id = {r["post_id"]: r for r in enriched}
    assert by_id["small"]["audience_adjusted_percentile"] > by_id["big"]["audience_adjusted_percentile"]
    assert by_id["small"]["audience_adjusted_zscore"] > by_id["big"]["audience_adjusted_zscore"]


def test_audience_adjusted_partial_coverage_ranks_only_valid_subset():
    """Partial profile-enrichment coverage (some authors matched, some not)
    must still rank the matched subset, leaving unmatched rows as None
    rather than failing the whole batch."""
    records = [
        _follower_record("has_followers_1", 100, 1000),
        _follower_record("has_followers_2", 10, 100),
        _follower_record("no_followers", 500, None),
    ]
    enriched = add_audience_adjusted_benchmark(records)
    by_id = {r["post_id"]: r for r in enriched}

    assert by_id["no_followers"]["audience_adjusted_percentile"] is None
    assert by_id["no_followers"]["audience_adjusted_zscore"] is None
    assert by_id["has_followers_1"]["audience_adjusted_percentile"] is not None
    assert by_id["has_followers_2"]["audience_adjusted_percentile"] is not None


def test_audience_adjusted_treats_zero_follower_count_as_missing():
    records = [_follower_record("zero", 100, 0), _follower_record("valid", 100, 100)]
    enriched = add_audience_adjusted_benchmark(records)
    by_id = {r["post_id"]: r for r in enriched}
    assert by_id["zero"]["audience_adjusted_percentile"] is None
    assert by_id["valid"]["audience_adjusted_percentile"] is not None


# ── compute_neighbor_prediction ──────────────────────────────────────────────

def _neighbor(**kwargs):
    defaults = {
        "engagement_percentile": 50.0,
        "likes": 80,
        "comments": 15,
        "shares": 5,
        "total_engagement": 100,
        "cosine_distance": 0.05,
        "audience_adjusted_percentile": None,
        "engagement_rate": None,
        "follower_count": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_compute_neighbor_prediction_empty_neighbors():
    result = compute_neighbor_prediction([])
    assert result["percentile"] == 50.0
    assert result["neighbor_count"] == 0
    assert result["method"] == "raw_fallback"
    assert result["predicted_likes"] == 0
    assert result["predicted_comments"] == 0
    assert result["predicted_shares"] == 0


def test_compute_neighbor_prediction_prefers_audience_adjusted_when_majority_have_it():
    posts = [
        _neighbor(audience_adjusted_percentile=90.0, engagement_percentile=40.0),
        _neighbor(audience_adjusted_percentile=80.0, engagement_percentile=30.0),
        _neighbor(audience_adjusted_percentile=70.0, engagement_percentile=20.0),
    ]
    result = compute_neighbor_prediction(posts)
    assert result["method"] == "audience_adjusted"
    assert result["coverage"] == 3
    assert result["percentile"] > 70.0


def test_compute_neighbor_prediction_falls_back_to_raw_when_sparse_coverage():
    posts = [
        _neighbor(audience_adjusted_percentile=90.0, engagement_percentile=40.0),
        _neighbor(engagement_percentile=20.0),
        _neighbor(engagement_percentile=30.0),
    ]
    result = compute_neighbor_prediction(posts)
    assert result["method"] == "raw_fallback"
    assert result["coverage"] == 1


def test_compute_neighbor_prediction_scales_total_engagement_with_draft_followers():
    posts = [
        _neighbor(
            engagement_rate=0.1,
            follower_count=1000,
            total_engagement=100,
            likes=80,
            comments=15,
            shares=5,
            engagement_percentile=50.0,
        ),
        _neighbor(
            engagement_rate=0.2,
            follower_count=1000,
            total_engagement=200,
            likes=160,
            comments=30,
            shares=10,
            engagement_percentile=60.0,
        ),
    ]
    result = compute_neighbor_prediction(posts, draft_follower_count=500)
    assert result["total_engagement_estimate"] == 75
    assert (
        result["predicted_likes"]
        + result["predicted_comments"]
        + result["predicted_shares"]
        == result["total_engagement_estimate"]
    )


def test_compute_neighbor_prediction_includes_reconciled_breakdown():
    posts = [
        _neighbor(likes=100, comments=20, shares=10, total_engagement=130),
        _neighbor(likes=50, comments=10, shares=5, total_engagement=65),
    ]
    result = compute_neighbor_prediction(posts)
    assert result["predicted_likes"] >= 0
    assert result["predicted_comments"] >= 0
    assert result["predicted_shares"] >= 0
    assert (
        result["predicted_likes"]
        + result["predicted_comments"]
        + result["predicted_shares"]
        == result["total_engagement_estimate"]
    )


def test_compute_neighbor_engagement_breakdown_reconciles_to_total():
    posts = [
        _neighbor(likes=90, comments=8, shares=2, total_engagement=100),
        _neighbor(likes=45, comments=4, shares=1, total_engagement=50),
    ]
    breakdown = compute_neighbor_engagement_breakdown(posts, total_engagement_estimate=99)
    assert breakdown["predicted_likes"] + breakdown["predicted_comments"] + breakdown["predicted_shares"] == 99


# ── flag_engagement_anomalies ───────────────────────────────────────────────

def _ratio_record(post_id: str, comment_ratio=None, share_ratio=None) -> dict:
    return {"post_id": post_id, "comment_ratio": comment_ratio, "share_ratio": share_ratio}


def test_flag_empty_input_returns_empty_list():
    assert flag_engagement_anomalies([]) == []


def test_flag_does_not_mutate_input_records():
    records = [_ratio_record("1", comment_ratio=0.1), _ratio_record("2", comment_ratio=0.5)]
    original_copy = [dict(r) for r in records]
    flag_engagement_anomalies(records)
    assert records == original_copy


def test_flag_adds_default_false_flag_and_empty_reasons_when_nothing_is_anomalous():
    records = [
        _ratio_record("1", comment_ratio=0.10),
        _ratio_record("2", comment_ratio=0.11),
        _ratio_record("3", comment_ratio=0.09),
        _ratio_record("4", comment_ratio=0.12),
    ]
    enriched = flag_engagement_anomalies(records)
    for record in enriched:
        assert record["engagement_anomaly_flag"] is False
        assert record["anomaly_reasons"] == []


def test_flag_catches_a_clear_comment_ratio_outlier():
    records = [
        _ratio_record("1", comment_ratio=0.10),
        _ratio_record("2", comment_ratio=0.11),
        _ratio_record("3", comment_ratio=0.09),
        _ratio_record("4", comment_ratio=0.12),
        _ratio_record("5", comment_ratio=0.10),
        _ratio_record("outlier", comment_ratio=5.0),
    ]
    enriched = flag_engagement_anomalies(records)
    by_id = {r["post_id"]: r for r in enriched}

    assert by_id["outlier"]["engagement_anomaly_flag"] is True
    assert "comment_ratio_outlier" in by_id["outlier"]["anomaly_reasons"]

    for post_id in ("1", "2", "3", "4", "5"):
        assert by_id[post_id]["engagement_anomaly_flag"] is False


def test_flag_uniform_batch_produces_no_false_positives():
    # Every value identical -> MAD is 0 -> guarded against div-by-zero, and
    # nothing should be flagged (there's no variation to be an outlier from).
    records = [_ratio_record(str(i), comment_ratio=0.2) for i in range(5)]
    enriched = flag_engagement_anomalies(records)
    assert all(r["engagement_anomaly_flag"] is False for r in enriched)


def test_flag_none_ratios_are_skipped_not_flagged():
    records = [
        _ratio_record("1", comment_ratio=None),
        _ratio_record("2", comment_ratio=0.10),
        _ratio_record("3", comment_ratio=0.11),
    ]
    enriched = flag_engagement_anomalies(records)
    by_id = {r["post_id"]: r for r in enriched}
    assert by_id["1"]["engagement_anomaly_flag"] is False
    assert by_id["1"]["anomaly_reasons"] == []


def test_flag_checks_share_ratio_independently_of_comment_ratio():
    records = [
        _ratio_record("1", comment_ratio=0.1, share_ratio=0.05),
        _ratio_record("2", comment_ratio=0.1, share_ratio=0.06),
        _ratio_record("3", comment_ratio=0.1, share_ratio=0.04),
        _ratio_record("4", comment_ratio=0.1, share_ratio=0.05),
        _ratio_record("outlier", comment_ratio=0.1, share_ratio=10.0),
    ]
    enriched = flag_engagement_anomalies(records)
    by_id = {r["post_id"]: r for r in enriched}
    assert by_id["outlier"]["engagement_anomaly_flag"] is True
    assert "share_ratio_outlier" in by_id["outlier"]["anomaly_reasons"]
    assert "comment_ratio_outlier" not in by_id["outlier"]["anomaly_reasons"]
