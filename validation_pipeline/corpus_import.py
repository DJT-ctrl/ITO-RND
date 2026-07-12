"""Load saved Scraper Stage collections into the validation pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config.paths import resolve_data_path
from config.settings import Settings, load_settings
from processors.profile_enricher import enrich_posts_with_follower_data
from processors.profile_sources import find_paired_profile_file
from storage.vector_store import create_schema, get_connection
from validation_pipeline.collect import raw_posts_to_collected
from validation_pipeline.predict import predict_for_post, save_prediction
from validation_pipeline.schemas import CollectedPost, PredictionRecord
from validation_pipeline.store import prediction_exists


class CorpusImportResult(BaseModel):
    imported: int = 0
    skipped: int = 0
    predictions: list[PredictionRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def list_saved_collections(settings: Settings) -> list[Path]:
    """Same linkedin_*.json post scans as Scraper Stage (data/raw by default)."""
    data_dir = resolve_data_path(settings.raw_data_dir)
    if not data_dir.exists():
        return []
    return sorted(
        (f for f in data_dir.glob("linkedin_*.json") if "profiles" not in f.name),
        reverse=True,
    )


def collected_posts_from_saved_collection(
    collection_path: Path | str,
    settings: Settings,
    *,
    max_posts: int | None = None,
) -> list[CollectedPost]:
    """Load a Scraper Stage post JSON and pair it with profiles when available."""
    path = Path(collection_path)
    raw_posts: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if max_posts is not None:
        raw_posts = raw_posts[:max_posts]

    paired = find_paired_profile_file(path, settings.raw_data_dir)
    profile_records: list[dict[str, Any]] = []
    if paired and paired.exists():
        profile_records = json.loads(paired.read_text(encoding="utf-8"))

    enriched = enrich_posts_with_follower_data(raw_posts, profile_records)
    return raw_posts_to_collected(enriched, settings, skip_min_age=True)


async def predict_on_posts_async(
    posts: list[CollectedPost],
    settings: Settings,
    *,
    due_immediately: bool = True,
    skip_existing: bool = True,
) -> CorpusImportResult:
    """Run the predictor on pre-loaded posts and schedule validation."""
    result = CorpusImportResult()
    due_at = datetime.now(timezone.utc) if due_immediately else None

    for post in posts:
        if skip_existing:
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
            result.imported += 1
            result.predictions.append(saved)
        except Exception as exc:
            result.errors.append(f"{post.linkedin_post_id}: {exc}")

    return result


def predict_on_posts(
    posts: list[CollectedPost],
    settings: Settings | None = None,
    **kwargs: Any,
) -> CorpusImportResult:
    settings = settings or load_settings()
    return asyncio.run(predict_on_posts_async(posts, settings, **kwargs))
