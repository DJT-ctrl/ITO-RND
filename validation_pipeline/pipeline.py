"""End-to-end collect + predict orchestration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from config.settings import Settings, load_settings
from storage.vector_store import create_schema, get_connection
from validation_pipeline.collect import collect_posts
from validation_pipeline.predict import predict_for_post, save_prediction
from validation_pipeline.schemas import CollectedPost, CollectPredictResult
from validation_pipeline.store import prediction_exists

# Brief pause between posts to avoid hammering Gemini during batch validation runs.
_INTER_POST_DELAY_S = 1.0


async def _predict_posts(
    posts: list[CollectedPost],
    settings: Settings,
    *,
    due_immediately: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    result = CollectPredictResult()
    result.scraped = len(posts)
    due_at = datetime.now(timezone.utc) if due_immediately else None

    for i, post in enumerate(posts, start=1):
        if on_progress:
            on_progress(f"Predicting {i}/{len(posts)}: {post.linkedin_post_id}")
        conn = get_connection(settings)
        try:
            create_schema(conn)
            if prediction_exists(conn, post.linkedin_post_id):
                result.skipped += 1
                continue
        finally:
            conn.close()
        try:
            prediction = await predict_for_post(post, settings)
            saved = save_prediction(
                post,
                prediction,
                settings,
                validation_due_at=due_at,
            )
            result.predicted += 1
            result.predictions.append(saved)
        except Exception as exc:
            result.errors.append(f"{post.linkedin_post_id}: {exc}")

        if i < len(posts):
            await asyncio.sleep(_INTER_POST_DELAY_S)

    return result


async def run_collect_and_predict(
    search_params: dict[str, Any],
    *,
    settings: Settings | None = None,
    profile_url_limit: int | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    """Scrape posts, predict each, and schedule validation."""
    settings = settings or load_settings()
    posts = collect_posts(
        search_params,
        settings=settings,
        profile_url_limit=profile_url_limit,
        on_progress=on_progress,
    )
    return await _predict_posts(posts, settings, on_progress=on_progress)


async def run_predict_on_posts(
    posts: list[CollectedPost],
    *,
    settings: Settings | None = None,
    due_immediately: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> CollectPredictResult:
    """Predict and schedule validation for already-loaded posts (no Apify scrape)."""
    settings = settings or load_settings()
    return await _predict_posts(
        posts,
        settings,
        due_immediately=due_immediately,
        on_progress=on_progress,
    )


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
