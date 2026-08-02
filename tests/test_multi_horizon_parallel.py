"""Tests for parallel multi-horizon predict workers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from validation_pipeline.age_buckets import LANE_SAME_AGE
from validation_pipeline.multi_horizon import run_multi_horizon_on_posts
from validation_pipeline.schemas import CollectedPost, PredictionRecord


def _post(post_id: str) -> CollectedPost:
    return CollectedPost(
        linkedin_post_id=post_id,
        linkedin_url=f"https://linkedin.com/posts/{post_id}",
        content="hello world " * 20,
        posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        scraped_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        likes=10,
        comments=2,
        shares=1,
        total_engagement=13,
    )


def test_run_multi_horizon_uses_parallel_workers():
    posts = [_post(f"p{i}") for i in range(5)]
    settings = MagicMock()
    settings.validation_multi_horizon_enabled = True
    settings.validation_multi_horizon_max_predicts_per_run = 10
    settings.validation_predict_workers = 3
    settings.validation_fixed_horizon_enabled = False

    concurrent = {"n": 0, "max": 0}
    lock = asyncio.Lock()

    async def fake_predict(post, settings, **kwargs):
        async with lock:
            concurrent["n"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["n"])
        await asyncio.sleep(0.05)
        async with lock:
            concurrent["n"] -= 1
        record = MagicMock(spec=PredictionRecord)
        record.prediction_horizon_hours = 24.0
        record.prediction_lane = LANE_SAME_AGE
        record.linkedin_post_id = post.linkedin_post_id
        record.prediction_id = uuid4()
        return [record], [], 0

    mock_conn = MagicMock()

    async def _run():
        with (
            patch(
                "validation_pipeline.multi_horizon.get_connection",
                return_value=mock_conn,
            ),
            patch("validation_pipeline.multi_horizon.create_schema"),
            patch(
                "validation_pipeline.store.existing_prediction_lanes_and_keys",
                return_value=(set(), set()),
            ),
            patch(
                "validation_pipeline.multi_horizon.predict_multi_horizon_for_post",
                new=AsyncMock(side_effect=fake_predict),
            ),
            patch(
                "validation_pipeline.multi_horizon.planned_horizons_for_post",
                return_value=[(LANE_SAME_AGE, 24)],
            ),
        ):
            return await run_multi_horizon_on_posts(posts, settings=settings)

    result = asyncio.run(_run())
    assert result.predicted == 5
    assert concurrent["max"] >= 2  # exercised concurrency (workers=3)
    assert concurrent["max"] <= 3
