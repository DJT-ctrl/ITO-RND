"""Unit tests for the batch engagement benchmark (processors/benchmark.py)."""

from processors.benchmark import add_engagement_benchmark, flag_engagement_anomalies


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
