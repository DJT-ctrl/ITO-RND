"""Load saved Scraper Stage collections into the validation pipeline."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from config.paths import resolve_data_path
from config.settings import Settings, load_settings
from processors.profile_enricher import enrich_posts_with_follower_data
from processors.profile_sources import find_paired_profile_file
from storage.vector_store import create_schema, get_connection
from validation_pipeline.collect import raw_posts_to_collected
from validation_pipeline.predict import predict_for_post, save_prediction
from validation_pipeline.schemas import CollectedPost, PredictionRecord
from validation_pipeline.store import existing_prediction_post_ids, prediction_exists

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


def partition_posts_by_existing_predictions(
    posts: list[CollectedPost],
    settings: Settings,
) -> tuple[list[CollectedPost], list[CollectedPost]]:
    """Split posts into (pending, already_predicted) using the predictions table.

    Multi-horizon completeness:
    - Lane A (``same_age``): satisfied if *any* same_age row exists for the post
      (exact hour must not drift as wall-clock age ticks).
    - Lane B (fixed horizons): each planned future fixed horizon must exist.
    """
    if not posts:
        return [], []
    conn = get_connection(settings)
    try:
        create_schema(conn)
        if settings.validation_multi_horizon_enabled:
            from validation_pipeline.multi_horizon import planned_horizons_for_post
            from validation_pipeline.age_buckets import LANE_FIXED_HORIZON, LANE_SAME_AGE
            from validation_pipeline.store import existing_prediction_lanes_and_keys

            keys, same_age_posts = existing_prediction_lanes_and_keys(
                conn, [post.linkedin_post_id for post in posts]
            )
            pending: list[CollectedPost] = []
            already: list[CollectedPost] = []
            for post in posts:
                planned = planned_horizons_for_post(post, settings)
                missing = False
                for lane, horizon in planned:
                    if lane == LANE_SAME_AGE:
                        if post.linkedin_post_id not in same_age_posts:
                            missing = True
                            break
                        continue
                    if lane == LANE_FIXED_HORIZON:
                        if (post.linkedin_post_id, float(horizon)) not in keys:
                            missing = True
                            break
                if missing:
                    pending.append(post)
                else:
                    already.append(post)
            return pending, already

        existing = existing_prediction_post_ids(
            conn,
            [post.linkedin_post_id for post in posts],
        )
    finally:
        conn.close()

    pending = []
    already = []
    for post in posts:
        if post.linkedin_post_id in existing:
            already.append(post)
        else:
            pending.append(post)
    return pending, already


@dataclass(frozen=True)
class PredictionProgressCounts:
    """Collect-page progress: mutually exclusive post buckets."""

    total: int = 0
    done: int = 0
    waiting: int = 0
    remaining: int = 0


def prediction_progress_counts(
    posts: list[CollectedPost],
    settings: Settings,
) -> PredictionProgressCounts:
    """Count Done / Waiting / Remaining for vectorized posts.

    - **Done**: has prediction(s) and nothing still ``scheduled`` (graded).
    - **Waiting**: has at least one ``scheduled`` row (Lane B rescrape pending).
    - **Remaining**: no predictions yet (still need Gemini predict).
    """
    if not posts:
        return PredictionProgressCounts()
    if not settings.database_url:
        return PredictionProgressCounts(total=len(posts), remaining=len(posts))

    from validation_pipeline.store import prediction_post_coverage

    # Do not run create_schema here — Collect page loads this often, and schema
    # migrate over a slow tunnel blocks the UI for minutes.
    conn = get_connection(settings)
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '8000'")
        coverage = prediction_post_coverage(
            conn, [post.linkedin_post_id for post in posts]
        )
    finally:
        conn.close()

    done = waiting = remaining = 0
    for post in posts:
        flags = coverage.get(post.linkedin_post_id)
        if not flags or not flags.get("has_any"):
            remaining += 1
        elif flags.get("has_scheduled"):
            waiting += 1
        else:
            done += 1
    return PredictionProgressCounts(
        total=len(posts),
        done=done,
        waiting=waiting,
        remaining=remaining,
    )


def count_already_predicted(posts: list[CollectedPost], settings: Settings) -> int:
    """How many of *posts* are complete for the current multi-horizon plan."""
    if not posts:
        return 0
    _, already = partition_posts_by_existing_predictions(posts, settings)
    return len(already)

def select_posts_for_predict(
    posts: list[CollectedPost],
    settings: Settings,
    *,
    max_posts: int | None = None,
    skip_existing: bool = True,
) -> tuple[list[CollectedPost], int]:
    """Drop already-predicted posts (when enabled), then apply *max_posts*.

    Returns ``(selected_posts, skipped_count)``. Skipping before the cap means
    re-runs advance to new posts instead of reloading the same already-done
    head of the corpus.
    """
    skipped = 0
    selected = posts
    if skip_existing:
        selected, already = partition_posts_by_existing_predictions(selected, settings)
        skipped = len(already)
    if max_posts is not None:
        selected = selected[:max_posts]
    return selected, skipped


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
    validation_window_hours: float | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> CorpusImportResult:
    """Run the predictor on pre-loaded posts and schedule validation.

    When multi-horizon is enabled (default), creates Lane A + Lane B rows.
    ``on_progress`` receives ``(completed, total, message)`` after each post
    attempt (predict, skip, or error).
    """
    result = CorpusImportResult(loaded=len(posts))
    total = len(posts)

    def _report(completed: int, message: str) -> None:
        if on_progress:
            on_progress(completed, total, message)

    if total == 0:
        _report(0, "No posts to predict")
        return result

    if settings.validation_multi_horizon_enabled and not is_backtest:
        from validation_pipeline.multi_horizon import run_multi_horizon_on_posts

        last_completed = [0]

        def _mh_progress(message: str) -> None:
            """Bridge multi-horizon str callbacks → (completed, total, message).

            Batch loop emits ``Multi-horizon i/n: …`` at the start of each post
            and ``Multi-horizon i/n done: …`` after it finishes. Per-horizon
            lines keep the last completed count so the bar does not reset to 0.
            """
            if message.startswith("Multi-horizon ") and "/" in message:
                try:
                    head, _, tail = message.partition(":")
                    nums = head[len("Multi-horizon ") :].replace(" done", "").strip()
                    cur, _tot = (int(part) for part in nums.split("/", 1))
                    completed = (
                        cur if head.rstrip().endswith("done") else max(0, cur - 1)
                    )
                    last_completed[0] = completed
                    label = tail.strip() or message
                    _report(completed, f"{cur}/{_tot} — {label}")
                    return
                except (ValueError, IndexError):
                    pass
            _report(last_completed[0], message)

        mh = await run_multi_horizon_on_posts(
            posts, settings=settings, on_progress=_mh_progress
        )
        result.imported = mh.predicted
        result.skipped = mh.skipped
        result.predictions = mh.predictions
        result.errors = mh.errors
        _report(
            total,
            f"Done — imported={result.imported} skipped={result.skipped} "
            f"budget_skipped={mh.budget_skipped} errors={len(result.errors)}",
        )
        return result

    due_at = datetime.now(timezone.utc) if due_immediately else None
    horizon = (
        float(validation_window_hours)
        if validation_window_hours is not None
        else float(settings.validation_window_hours)
    )
    _report(0, f"Starting predict for {total} post(s)...")

    for index, post in enumerate(posts, start=1):
        label = post.linkedin_post_id or f"post-{index}"
        _report(index - 1, f"Predicting {index}/{total}: {label}")

        if skip_existing:
            conn = get_connection(settings)
            try:
                create_schema(conn)
                if prediction_exists(conn, post.linkedin_post_id, horizon):
                    result.skipped += 1
                    _report(index, f"Skipped {index}/{total}: {label} (already predicted)")
                    continue
            finally:
                conn.close()

        try:
            prediction = await predict_for_post(
                post,
                settings,
                target_horizon_hours=horizon,
                prediction_lane="fixed_horizon",
            )
            saved = save_prediction(
                post,
                prediction,
                settings,
                validation_due_at=due_at,
                is_backtest=is_backtest,
                validation_window_hours=horizon,
                prediction_lane="fixed_horizon",
            )
            result.imported += 1
            result.predictions.append(saved)
            _report(index, f"Predicted {index}/{total}: {label}")
        except Exception as exc:
            result.errors.append(f"{post.linkedin_post_id}: {exc}")
            _report(index, f"Error {index}/{total}: {label}")

        if inter_post_delay_s > 0 and index < total:
            await asyncio.sleep(inter_post_delay_s)

    _report(
        total,
        f"Done — imported={result.imported} skipped={result.skipped} errors={len(result.errors)}",
    )
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
    validation_window_hours: float | None = None,
) -> CorpusImportResult:
    """Discover saved scrapes, dedupe, predict, and schedule validation."""
    posts, source_files = load_all_collected_posts(
        settings,
        source=source,
        max_posts=None,
        extra_paths=extra_paths,
    )
    posts, skipped_existing = select_posts_for_predict(
        posts,
        settings,
        max_posts=max_posts,
        skip_existing=skip_existing,
    )
    result = await predict_on_posts_async(
        posts,
        settings,
        due_immediately=due_immediately,
        skip_existing=skip_existing,
        validation_window_hours=validation_window_hours,
    )
    result.skipped += skipped_existing
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
