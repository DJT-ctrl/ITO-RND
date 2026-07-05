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
is a better long-term benchmark, but it needs each post paired with a
profile scrape — the current raw dataset doesn't have that pairing yet.
``processors/schemas.py`` reserves a nullable field for it so adding it
later doesn't break the schema. See /memories/session/plan.md for the
decision to defer this.
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
    mean = sum(log_values) / len(log_values)
    variance = sum((value - mean) ** 2 for value in log_values) / len(log_values)
    std_dev = math.sqrt(variance)
    sorted_log_values = sorted(log_values)

    enriched_records = []
    for record, log_value in zip(records, log_values):
        enriched_records.append(
            {
                **record,
                "engagement_percentile": _percentile_rank(sorted_log_values, log_value),
                "engagement_zscore": round((log_value - mean) / std_dev, 4) if std_dev > 0 else 0.0,
            }
        )
    return enriched_records


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
