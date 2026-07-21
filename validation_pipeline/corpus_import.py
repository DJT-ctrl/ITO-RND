"""Load saved Scraper Stage collections into the validation pipeline."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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

ImportSourceKind = Literal["raw", "validation", "all"]


class CorpusImportResult(BaseModel):
    loaded: int = 0
    imported: int = 0
    skipped: int = 0
    source_files: list[str] = Field(default_factory=list)
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


def list_validation_collect_files(settings: Settings) -> list[Path]:
    """Validation collect artifacts saved during live scrape runs."""
    data_dir = resolve_data_path(settings.validation_data_dir)
    if not data_dir.exists():
        return []
    return sorted(data_dir.glob("collect_*.json"), reverse=True)


def list_import_source_files(
    settings: Settings,
    *,
    source: ImportSourceKind = "all",
) -> list[Path]:
    """Return scrape JSON files for bulk import, newest first within each group."""
    paths: list[Path] = []
    if source in ("raw", "all"):
        paths.extend(list_saved_collections(settings))
    if source in ("validation", "all"):
        paths.extend(list_validation_collect_files(settings))
    return paths


def dedupe_collected_posts(posts: list[CollectedPost]) -> list[CollectedPost]:
    """Keep the first occurrence of each linkedin_post_id."""
    seen: set[str] = set()
    unique: list[CollectedPost] = []
    for post in posts:
        if post.linkedin_post_id in seen:
            continue
        seen.add(post.linkedin_post_id)
        unique.append(post)
    return unique


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


def collected_posts_from_validation_collect(
    collection_path: Path | str,
    settings: Settings,
    *,
    max_posts: int | None = None,
) -> list[CollectedPost]:
    """Load posts from validation collect_*.json (already profile-enriched)."""
    path = Path(collection_path)
    raw_posts: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if max_posts is not None:
        raw_posts = raw_posts[:max_posts]
    return raw_posts_to_collected(raw_posts, settings, skip_min_age=True)


def load_collected_posts_from_paths(
    paths: list[Path | str],
    settings: Settings,
) -> tuple[list[CollectedPost], list[str]]:
    """Load and dedupe posts from multiple scrape JSON files."""
    collected: list[CollectedPost] = []
    source_files: list[str] = []

    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue

        try:
            if path.name.startswith("collect_"):
                posts = collected_posts_from_validation_collect(path, settings)
            else:
                posts = collected_posts_from_saved_collection(path, settings)
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"Could not load {path}: {exc}") from exc

        if posts:
            source_files.append(str(path))
            collected.extend(posts)

    return dedupe_collected_posts(collected), source_files


def load_all_collected_posts(
    settings: Settings,
    *,
    source: ImportSourceKind = "all",
    max_posts: int | None = None,
    extra_paths: list[Path | str] | None = None,
) -> tuple[list[CollectedPost], list[str]]:
    """Discover scrape files, load posts, dedupe, and optionally cap the total."""
    paths = list_import_source_files(settings, source=source)
    if extra_paths:
        paths = list(dict.fromkeys([*paths, *[Path(p) for p in extra_paths]]))

    posts, source_files = load_collected_posts_from_paths(paths, settings)
    if max_posts is not None:
        posts = posts[:max_posts]
    return posts, source_files


async def predict_on_posts_async(
    posts: list[CollectedPost],
    settings: Settings,
    *,
    due_immediately: bool = False,
    skip_existing: bool = True,
    inter_post_delay_s: float = 1.0,
    is_backtest: bool = False,
) -> CorpusImportResult:
    """Run the predictor on pre-loaded posts and schedule validation."""
    result = CorpusImportResult(loaded=len(posts))
    due_at = datetime.now(timezone.utc) if due_immediately else None

    for index, post in enumerate(posts, start=1):
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
                is_backtest=is_backtest,
            )
            result.imported += 1
            result.predictions.append(saved)
        except Exception as exc:
            result.errors.append(f"{post.linkedin_post_id}: {exc}")

        if inter_post_delay_s > 0 and index < len(posts):
            await asyncio.sleep(inter_post_delay_s)

    return result


def predict_on_posts(
    posts: list[CollectedPost],
    settings: Settings | None = None,
    **kwargs: Any,
) -> CorpusImportResult:
    settings = settings or load_settings()
    return asyncio.run(predict_on_posts_async(posts, settings, **kwargs))


async def bulk_import_and_predict_async(
    settings: Settings,
    *,
    source: ImportSourceKind = "all",
    max_posts: int | None = None,
    extra_paths: list[Path | str] | None = None,
    due_immediately: bool = False,
    skip_existing: bool = True,
) -> CorpusImportResult:
    """Discover saved scrapes, dedupe, predict, and schedule validation."""
    posts, source_files = load_all_collected_posts(
        settings,
        source=source,
        max_posts=max_posts,
        extra_paths=extra_paths,
    )
    result = await predict_on_posts_async(
        posts,
        settings,
        due_immediately=due_immediately,
        skip_existing=skip_existing,
    )
    result.source_files = source_files
    return result


def bulk_import_and_predict(
    settings: Settings | None = None,
    **kwargs: Any,
) -> CorpusImportResult:
    settings = settings or load_settings()
    return asyncio.run(bulk_import_and_predict_async(settings, **kwargs))


# Re-export vectorized bulk import (canonical definitions live in vectorized_corpus).
from validation_pipeline.vectorized_corpus import (  # noqa: E402
    bulk_import_vectorized_and_predict,
    bulk_import_vectorized_and_predict_async,
)
