"""Batch-level engagement benchmark computation.

Why a separate step from Stage 1
----------------------------------
``processors/post_analyser.py``'s Stage 1 computes per-post numbers
(``total_engagement``, ``comment_ratio``, ...) using only that single post's
data. A *benchmark* is different by definition: it only means something
relative to other posts. 50 likes is huge in a batch of quiet niche posts
and nothing in a batch of viral ones. That comparison requires the whole
batch at once, so it can't live in Stage 1 and has to run as its own step
after every post's Stage 1 features are computed.

Two scores are added to every record:
  engagement_percentile — where this post ranks (0-100) against the batch
  engagement_zscore     — how many standard deviations from the batch mean

Both are computed on ``log1p(total_engagement)`` rather than the raw count.
Social engagement counts are heavy-tailed (a handful of viral posts would
otherwise dominate the mean/std and compress every other post near zero);
the log transform keeps the benchmark meaningful across the whole range.

What's deliberately NOT here
-------------------------------
Follower-normalized ``engagement_rate`` (engagement / author follower count)
is computed in Stage 1 (processors/post_analyser.py) instead, since it's a
per-post ratio, not a batch comparison. The batch-level analogue lives here
as ``add_audience_adjusted_benchmark`` below — it's a SEPARATE, ADDITIVE
function (not folded into ``add_engagement_benchmark``) so the default
pipeline path (no ``--with-profile-enrichment``) never has to think about
follower counts at all.
"""

import math
from typing import Any


def add_engagement_benchmark(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a NEW list of records with engagement_percentile/_zscore added.

    Does not mutate the input list or its dicts. Every record must already
    have a ``total_engagement`` key (i.e. have been through Stage 1).

    An empty input returns an empty list rather than raising — callers
    (e.g. run_pipeline) are expected to guard against an empty dataset
    themselves with a more specific error message.
    """
    if not records:
        return []

    log_values = [math.log1p(record["total_engagement"]) for record in records]
    return _rank_by_score(records, log_values, "engagement_percentile", "engagement_zscore")


def add_audience_adjusted_benchmark(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a NEW list of records with audience_adjusted_percentile/_zscore
    added — an OPTIONAL, follower-normalized companion to
    ``add_engagement_benchmark``'s raw ranking (see T6_TEAM_PLAN.md Point 1:
    a creator with 1M followers gets thousands of views regardless of
    content quality, which skews a pure-engagement benchmark).

    Only meaningful for records with a positive ``follower_count`` (i.e.
    posts that went through the optional profile-enrichment path — see
    processors/run_pipeline.py's ``--with-profile-enrichment``). Records
    missing/invalid ``follower_count`` get ``None`` for both fields rather
    than being dropped, so a partially-enriched batch (some authors scraped,
    some not — see processors/profile_sources.py) still ranks the subset
    that CAN be ranked, instead of failing the whole batch.

    The ranked score is ``log1p(total_engagement) - log1p(follower_count)``
    (both log-transformed for the same heavy-tail reason as the raw
    benchmark) — NOT the plain ``engagement_rate`` ratio Stage 1 stores,
    which is kept as the simple, human-readable display metric instead.

    Does not mutate the input. Empty input returns an empty list.
    """
    if not records:
        return []

    valid_indices = [
        i for i, r in enumerate(records) if (r.get("follower_count") or 0) > 0
    ]
    if not valid_indices:
        return [{**r, "audience_adjusted_percentile": None, "audience_adjusted_zscore": None} for r in records]

    valid_records = [records[i] for i in valid_indices]
    scores = [
        math.log1p(r["total_engagement"]) - math.log1p(r["follower_count"]) for r in valid_records
    ]
    ranked_valid = _rank_by_score(
        valid_records, scores, "audience_adjusted_percentile", "audience_adjusted_zscore"
    )

    ranked_by_index = dict(zip(valid_indices, ranked_valid))
    return [
        ranked_by_index[i] if i in ranked_by_index else {**r, "audience_adjusted_percentile": None, "audience_adjusted_zscore": None}
        for i, r in enumerate(records)
    ]


def _rank_by_score(
    records: list[dict[str, Any]],
    scores: list[float],
    percentile_key: str,
    zscore_key: str,
) -> list[dict[str, Any]]:
    """Shared percentile/z-score computation used by both benchmark
    functions above — same heavy-tailed-safe math, different output keys.
    """
    mean = sum(scores) / len(scores)
    variance = sum((value - mean) ** 2 for value in scores) / len(scores)
    std_dev = math.sqrt(variance)
    sorted_scores = sorted(scores)

    return [
        {
            **record,
            percentile_key: _percentile_rank(sorted_scores, score),
            zscore_key: round((score - mean) / std_dev, 4) if std_dev > 0 else 0.0,
        }
        for record, score in zip(records, scores)
    ]



def _percentile_rank(sorted_values: list[float], value: float) -> float:
    """% of the batch this value is greater than or equal to, 0-100.

    Uses "mean rank" so exact ties (e.g. several posts with 0 engagement)
    split the percentile evenly between them instead of arbitrarily
    favouring whichever happened to come first in the list.
    """
    count_below = sum(1 for v in sorted_values if v < value)
    count_equal = sum(1 for v in sorted_values if v == value)
    rank = count_below + count_equal / 2
    return round(100 * rank / len(sorted_values), 2)


def flag_engagement_anomalies(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a NEW list of records with engagement_anomaly_flag/anomaly_reasons added.

    Why this exists
    -----------------
    A percentile/z-score tells you *where* a post ranks, not whether its
    engagement looks organic. Bot/engagement-pod pollution and adversarial
    data usually shows up as an implausible RATIO between engagement types
    (e.g. comments far out of proportion to likes) rather than a high total
    — a post can be perfectly ordinary in total_engagement terms and still
    have a bot-inflated comment_ratio.

    This flags each post's comment_ratio/share_ratio against the rest of
    the batch using a *modified z-score* (median + MAD, not mean + std).
    MAD is used deliberately: mean/std are themselves dragged around by the
    very outliers this is trying to catch, which would raise the bar right
    when it needs to be sensitive. Threshold 3.5 is the conservative cutoff
    from Iglewicz & Hoaglin's outlier-detection guidance (fewer false
    positives, appropriate for a dataset this small).

    Does not mutate the input. Every record must already have
    ``comment_ratio``/``share_ratio`` keys (i.e. have been through Stage 1)
    — either may be ``None`` (posts with 0 likes), which are simply
    excluded from that ratio's check rather than treated as anomalous.

    This function only FLAGS — it never drops or reorders records. Callers
    (processors/run_pipeline.py) are expected to route flagged records to a
    separate review file instead of the main dataset.
    """
    if not records:
        return []

    reasons_by_index: list[list[str]] = [[] for _ in records]
    ratio_checks = (
        ("comment_ratio", "comment_ratio_outlier"),
        ("share_ratio", "share_ratio_outlier"),
    )
    for field, reason_label in ratio_checks:
        indexed_values = [(i, r[field]) for i, r in enumerate(records) if r.get(field) is not None]
        if len(indexed_values) < 2:
            continue  # nothing meaningful to compare against

        values = [v for _, v in indexed_values]
        median = _median(values)
        mad = _median([abs(v - median) for v in values])
        if mad == 0:
            continue  # every value in this batch is identical for this ratio — nothing is an outlier

        for index, value in indexed_values:
            modified_zscore = 0.6745 * (value - median) / mad
            if abs(modified_zscore) > 3.5:
                reasons_by_index[index].append(reason_label)

    return [
        {
            **record,
            "engagement_anomaly_flag": bool(reasons_by_index[i]),
            "anomaly_reasons": reasons_by_index[i],
        }
        for i, record in enumerate(records)
    ]


def _median(values: list[float]) -> float:
    """Standard median (average of the two middle values on an even-length list)."""
    ordered = sorted(values)
    count = len(ordered)
    midpoint = count // 2
    if count % 2 == 0:
        return (ordered[midpoint - 1] + ordered[midpoint]) / 2
    return ordered[midpoint]
