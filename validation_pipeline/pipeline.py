"""End-to-end collect + predict orchestration."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from config.settings import Settings, load_settings
from validation_pipeline.collect import collect_posts
from validation_pipeline.predict import predict_and_save
from validation_pipeline.schemas import CollectPredictResult


async def run_collect_and_predict(
    search_params: dict[str, Any],
    *,
    settings: Settings | None = None,
    profile_url_limit: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    """Scrape posts, predict each, and schedule validation."""
    settings = settings or load_settings()
    result = CollectPredictResult()

    posts = collect_posts(
        search_params,
        settings=settings,
        profile_url_limit=profile_url_limit,
        on_progress=on_progress,
    )
    result.scraped = len(posts)

    for post in posts:
        try:
            saved = await predict_and_save(post, settings)
            if saved is None:
                result.skipped += 1
            else:
                result.predicted += 1
                result.predictions.append(saved)
        except Exception as exc:
            result.errors.append(f"{post.linkedin_post_id}: {exc}")

    return result


def run_collect_and_predict_sync(
    search_params: dict[str, Any],
    *,
    settings: Settings | None = None,
    profile_url_limit: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    return asyncio.run(
        run_collect_and_predict(
            search_params,
            settings=settings,
            profile_url_limit=profile_url_limit,
            on_progress=on_progress,
        )
    )
