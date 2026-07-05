"""Unit tests for the batch engagement benchmark (processors/benchmark.py)."""

from processors.benchmark import add_engagement_benchmark


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
