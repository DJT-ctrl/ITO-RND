"""Corpus percentile mapping and validation scoring for the prediction pipeline."""

from __future__ import annotations

import math
from typing import Optional, Sequence

import psycopg

from validation_pipeline.schemas import EngagementActuals, PredictionRecord, ValidationScores

MIN_CORPUS_SIZE = 30


def _percentile_rank(sorted_values: list[float], value: float) -> float:
    """Percentile rank 0-100 using mean-rank tie handling (matches benchmark.py)."""
    count_below = sum(1 for v in sorted_values if v < value)
    count_equal = sum(1 for v in sorted_values if v == value)
    rank = count_below + count_equal / 2
    return round(100 * rank / len(sorted_values), 2)


def fetch_corpus_engagement_totals(conn: psycopg.Connection) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT total_engagement FROM posts WHERE engagement_anomaly_flag = FALSE"
        )
        rows = cur.fetchall()
    return [int(row[0]) for row in rows]


def compute_corpus_percentile(
    total_engagement: int,
    corpus_totals: Sequence[int],
) -> float:
    """Map a total engagement count to a percentile against the corpus distribution."""
    if not corpus_totals:
        return 50.0
    log_values = sorted(math.log1p(max(0, value)) for value in corpus_totals)
    score = math.log1p(max(0, total_engagement))
    return _percentile_rank(log_values, score)


def _metric_delta(actual: int, predicted: Optional[int]) -> float:
    if predicted is None:
        return float(actual)
    return round(float(actual - predicted), 2)


def compute_validation_scores(
    actuals: EngagementActuals,
    prediction: PredictionRecord,
    corpus_totals: Sequence[int],
) -> ValidationScores:
    actual_percentile = compute_corpus_percentile(actuals.total_engagement, corpus_totals)
    delta = round(actual_percentile - prediction.predicted_engagement_percentile, 2)
    accuracy = round(max(0.0, 100.0 - abs(delta)), 2)
    return ValidationScores(
        actual_engagement_percentile=actual_percentile,
        prediction_delta=delta,
        accuracy_score=accuracy,
        corpus_sample_size=len(corpus_totals),
        likes_delta=_metric_delta(actuals.likes, prediction.predicted_likes),
        comments_delta=_metric_delta(actuals.comments, prediction.predicted_comments),
        shares_delta=_metric_delta(actuals.shares, prediction.predicted_shares),
        total_engagement_delta=_metric_delta(
            actuals.total_engagement, prediction.predicted_total_engagement
        ),
    )


def corpus_size_warning(corpus_totals: Sequence[int]) -> str | None:
    size = len(corpus_totals)
    if size < MIN_CORPUS_SIZE:
        return (
            f"Corpus has only {size} posts (minimum {MIN_CORPUS_SIZE} recommended). "
            "Percentiles may be unreliable."
        )
    return None
