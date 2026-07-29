"""Phase 11 age buckets, scoring helpers, and multi-horizon planning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from validation_pipeline.age_buckets import (
    LANE_FIXED_HORIZON,
    LANE_SAME_AGE,
    bucket_for_hours,
    horizon_learning_sql,
    same_age_horizon_hours,
)
from validation_pipeline.multi_horizon import planned_horizons_for_post
from validation_pipeline.schemas import CollectedPost
from validation_pipeline.scoring import compute_validation_scores
from validation_pipeline.schemas import EngagementActuals, PredictionRecord
from uuid import uuid4


def test_bucket_edges():
    assert bucket_for_hours(0) == "0_6"
    assert bucket_for_hours(5.9) == "0_6"
    assert bucket_for_hours(6) == "6_12"
    assert bucket_for_hours(24) == "24_36"
    assert bucket_for_hours(48) == "48_72"
    assert bucket_for_hours(72) == "72_168"
    assert bucket_for_hours(200) == "168_plus"
    assert bucket_for_hours(None) == "unknown"


def test_same_age_horizon_hours_minimum():
    assert same_age_horizon_hours(0.2) == 1
    assert same_age_horizon_hours(5.4) == 5
    assert same_age_horizon_hours(5.6) == 6


def test_horizon_learning_sql_disabled():
    clause, params = horizon_learning_sql(
        enabled=False, query_horizon_hours=48.0
    )
    assert clause == ""
    assert params == []


def test_horizon_learning_sql_48h_bucket():
    clause, params = horizon_learning_sql(
        enabled=True, query_horizon_hours=48.0, alias="p"
    )
    assert "prediction_horizon_hours" in clause
    assert params == [48.0, 72.0]


def test_planned_horizons_includes_same_age_and_fixed():
    now = datetime.now(timezone.utc)
    post = CollectedPost(
        linkedin_post_id="abc",
        linkedin_url="https://linkedin.com/feed/update/urn:li:activity:1",
        content="hello",
        posted_at=now - timedelta(hours=10),
        scraped_at=now,
        likes=10,
        comments=1,
        shares=0,
        total_engagement=11,
    )
    settings = MagicMock()
    settings.validation_fixed_horizons_hours = (24, 48, 72)
    jobs = planned_horizons_for_post(post, settings)
    assert jobs[0][0] == LANE_SAME_AGE
    assert jobs[0][1] == 10
    assert (LANE_FIXED_HORIZON, 48) in jobs
    assert (LANE_FIXED_HORIZON, 24) in jobs
    assert (LANE_FIXED_HORIZON, 72) in jobs


def test_planned_horizons_skips_elapsed_fixed_horizons_for_old_posts():
    """Bulk/backtest imports of already-old posts must not schedule Lane B
    rescrapes for horizons that already elapsed. Their due_at would collapse
    to "now" (see predict_multi_horizon_for_post), so the next worker tick
    would re-scrape and mislabel today's (mature) engagement as the
    24h/48h/72h number — exactly the age/horizon skew Phase 11 removes.
    Lane A already grades the post at its real current age instead.
    """
    now = datetime.now(timezone.utc)
    post = CollectedPost(
        linkedin_post_id="ancient",
        linkedin_url="https://linkedin.com/feed/update/urn:li:activity:9",
        content="hello",
        posted_at=now - timedelta(hours=500),
        scraped_at=now,
        likes=10,
        comments=1,
        shares=0,
        total_engagement=11,
    )
    settings = MagicMock()
    settings.validation_fixed_horizons_hours = (24, 48, 72)
    jobs = planned_horizons_for_post(post, settings)
    assert jobs == [(LANE_SAME_AGE, 500)]


def test_planned_horizons_keeps_only_future_fixed_horizons():
    now = datetime.now(timezone.utc)
    post = CollectedPost(
        linkedin_post_id="mid_age",
        linkedin_url="https://linkedin.com/feed/update/urn:li:activity:10",
        content="hello",
        posted_at=now - timedelta(hours=30),
        scraped_at=now,
        likes=10,
        comments=1,
        shares=0,
        total_engagement=11,
    )
    settings = MagicMock()
    settings.validation_fixed_horizons_hours = (24, 48, 72)
    jobs = planned_horizons_for_post(post, settings)
    assert (LANE_SAME_AGE, 30) in jobs
    assert (LANE_FIXED_HORIZON, 24) not in jobs
    assert (LANE_FIXED_HORIZON, 48) in jobs
    assert (LANE_FIXED_HORIZON, 72) in jobs


def test_compute_validation_scores_records_bucket_metadata():
    pred = PredictionRecord(
        prediction_id=uuid4(),
        linkedin_post_id="x",
        linkedin_url="https://example.com",
        content="c",
        posted_at=datetime.now(timezone.utc),
        predicted_engagement_percentile=50.0,
        validation_due_at=datetime.now(timezone.utc),
        prediction_horizon_hours=48.0,
    )
    actuals = EngagementActuals(likes=10, comments=0, shares=0, total_engagement=10)
    scores = compute_validation_scores(
        actuals,
        pred,
        [1, 5, 10, 20, 50],
        age_bucket="48_72",
        percentile_source="age_bucket",
        horizon_hours=48.0,
    )
    assert scores.age_bucket == "48_72"
    assert scores.percentile_source == "age_bucket"
    assert scores.corpus_sample_size == 5


def test_apply_soft_age_prefer_ranks_matching_bucket_first():
    from storage.similarity import apply_soft_age_prefer

    rows = [
        {"engagement_age_hours": 200.0, "cosine_distance": 0.01},
        {"engagement_age_hours": 50.0, "cosine_distance": 0.2},
        {"engagement_age_hours": None, "cosine_distance": 0.05},
    ]
    ranked = apply_soft_age_prefer(rows, prefer_age_hours=48.0, limit=3)
    assert ranked[0]["engagement_age_hours"] == 50.0


def test_predictor_prompt_includes_horizon():
    from agents.predictor import build_predictor_prompt
    from agents.schemas import EvaluationDeps

    deps = EvaluationDeps(
        draft_content="Draft text",
        target_horizon_hours=24.0,
        prediction_lane="fixed_horizon",
        age_bucket="24_36",
        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        neighbor_prediction={
            "percentile": 55.0,
            "total_engagement_estimate": 100,
            "predicted_likes": 80,
            "predicted_comments": 15,
            "predicted_shares": 5,
            "neighbor_count": 3,
            "coverage": 0,
            "method": "raw_fallback",
        },
    )
    prompt = build_predictor_prompt(deps)
    assert "24h after publish" in prompt
    assert "Do **not** assume a default 48-hour window" in prompt
    assert "Target horizon hours: 24" in prompt
